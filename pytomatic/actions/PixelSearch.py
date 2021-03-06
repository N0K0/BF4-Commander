import logging
import operator
import sys
from time import sleep

import numpy
import numpy as np
from PIL import ImageGrab
from PIL import Image
from numpy import single

from pytomatic.actions import Helpers
from ctypes import windll, c_int, c_uint, c_char_p, create_string_buffer
from struct import calcsize, pack
import win32con
import cv2
from matplotlib import pyplot as plt
from operator import itemgetter
from cv2.xfeatures2d import SIFT_create
import cv2

FORMAT = "%(levelname)s-%(module)s-Line %(lineno)s: %(message)s"


# logging.basicConfig(stream=sys.stderr, level=logging.DEBUG, format=FORMAT)

def extract_color_band(value, band):
    if band == 1 or band == 'R':
        return value >> 16
    elif band == 2 or band == 'G':
        return (value >> 8) & 0x0000FF
    elif band == 3 or band == 'B':
        return value & 0x0000FF
    else:
        raise ValueError('Invalid Bandinput')


class PixelSearch:
    class MouseEvent:
        def __init__(self):
            self.pos_start = ()
            self.pos_stop = ()
            self.state = None
            self.pos_box = None

        def __str__(self):
            string = f"""
            Start: {self.pos_start}
            Stop:  {self.pos_stop}
            State: {self.state}
            """.strip()

            out = ""
            for line in string.splitlines():
                out += line.strip() + "\n"

            return out

    def __init__(self, win_handler):
        self.wh = win_handler
        self.mouseEvent = self.MouseEvent()

    def pixel_search(self, color, shades=0, bbox=None, debug=None):
        logging.debug("Searching for the pixels with color {} and shade {} ".format(str(color), str(shades)))

        wnd_img = self.grab_window(file=debug, bbox=bbox)
        px_data = self.img_to_numpy(wnd_img)

        if bbox:
            px_data = px_data[bbox[0]:bbox[2], bbox[1]:bbox[3]]

        hits = self.find_pixel_in_array(px_data, color, shades)

        logging.debug("Found {} valid positions".format(np.count_nonzero(hits)))

        return hits

    def grab_screen(self, file=None, bbox=None):
        # TODO: Fix this brokenass shit (can only cap primary screen atm)
        # http://stackoverflow.com/questions/3585293/pil-imagegrab-fails-on-2nd-virtual-monitor-of-virtualbox
        temp_img = ImageGrab.grab(bbox)

        if file is not None:
            logging.debug("Saving image_name as {}".format('grab_' + file))
            temp_img.save('grab_' + file)

        return temp_img

    def grab_window(self, bbox=None, file=None):
        """
        Grabs the window and returns a image_name based on the on a hwnd and the
            bounding box that follows.

        Returns:
            PIL.Image.Image: Returns the image data grabbed by pillow
        """

        if self.wh.get_hwnd() is None and bbox is None:
            logging.error("You can not use grab grab_window without a windowhandler target or a BBOX")
            raise ReferenceError("You can not use grab grab_window without a windowhandler target or a BBOX")

        logging.debug("Trying to capture window")

        if bbox is None:
            hwnd = self.wh.get_hwnd()
            bbox = self.wh.create_boundingbox(hwnd)

        gdi32 = windll.gdi32
        # Win32 functions
        CreateDC = gdi32.CreateDCA
        CreateCompatibleDC = gdi32.CreateCompatibleDC
        GetDeviceCaps = gdi32.GetDeviceCaps
        CreateCompatibleBitmap = gdi32.CreateCompatibleBitmap
        BitBlt = gdi32.BitBlt
        SelectObject = gdi32.SelectObject
        GetDIBits = gdi32.GetDIBits
        DeleteDC = gdi32.DeleteDC
        DeleteObject = gdi32.DeleteObject

        # Win32 constants
        NULL = 0
        HORZRES = 8
        VERTRES = 10
        SRCCOPY = 13369376
        HGDI_ERROR = 4294967295
        ERROR_INVALID_PARAMETER = 87

        try:

            screen = CreateDC(c_char_p(b'DISPLAY'), NULL, NULL, NULL)
            screen_copy = CreateCompatibleDC(screen)

            if bbox:
                left, top, x2, y2 = bbox
                width = x2 - left + 1
                height = y2 - top + 1
            else:
                left = windll.user32.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
                top = windll.user32.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
                width = windll.user32.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
                height = windll.user32.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)

            bitmap = CreateCompatibleBitmap(screen, width, height)
            if bitmap == NULL:
                print('grab_screen: Error calling CreateCompatibleBitmap. Returned NULL')
                return

            hobj = SelectObject(screen_copy, bitmap)
            if hobj == NULL or hobj == HGDI_ERROR:
                print('grab_screen: Error calling SelectObject. Returned {0}.'.format(hobj))
                return

            if BitBlt(screen_copy, 0, 0, width, height, screen, left, top, SRCCOPY) == NULL:
                print('grab_screen: Error calling BitBlt. Returned NULL.')
                return

            bitmap_header = pack('LHHHH', calcsize('LHHHH'), width, height, 1, 24)
            bitmap_buffer = create_string_buffer(bitmap_header)
            bitmap_bits = create_string_buffer(b' ' * (height * ((width * 3 + 3) & -4)))
            got_bits = GetDIBits(screen_copy, bitmap, 0, height, bitmap_bits, bitmap_buffer, 0)
            if got_bits == NULL or got_bits == ERROR_INVALID_PARAMETER:
                print('grab_screen: Error calling GetDIBits. Returned {0}.'.format(got_bits))
                return

            image = Image.frombuffer('RGB', (width, height), bitmap_bits, 'raw', 'BGR', (width * 3 + 3) & -4, -1)
            return image
        finally:
            if bitmap is not None:
                if bitmap:
                    DeleteObject(bitmap)
                DeleteDC(screen_copy)
                DeleteDC(screen)

    def img_to_numpy(self, image):
        """
        Converts an PIL.Image object to a numpy array and then collapses the
            array into an rgb array

        Args:
            image_name (PIL.image_name): the image_name object to be converted

        Returns:
            A 2d/3d array with x*y elements. Each element represent a pixel with
            an RGB value. For example 0xab01ee  -> RGB (171,1,238) or simply by
            having R G B as the third dimension of the matrix
        """

        array = np.asarray(image, dtype="uint8")

        return array

    def find_pixel_in_array(self, numpy_array, color, shades=0):
        """
        Creates a bool array where values whose match color withing n shades are
            marked true.

        Args:
            numpy_array (NDarray): The array we are going to search.

            color (numpy.uint32): The color we are looking for.

            shades (int): Defines the tolerance per rgb color which still
                evaluates to True

        Returns:
            A boolean array where the pixels that has aproximate the value of
                color is set to True

        """

        if len(numpy_array.shape) == 3:  # TODO: Either use Vectorization or some inline C magic
            logging.debug('Got a expanded RGB array')
            ret = self.aproximate_color_3d(numpy_array, color, shades)
            ret = np.all(ret, axis=2)
            return ret

        elif len(numpy_array.shape) == 2:
            logging.debug('Got a compound RGB array')

            aprox = np.vectorize(self.aproximate_color_2d)
            array = aprox(numpy_array, color, shades)

        else:
            logging.debug('WTF did i just get?')
            raise TypeError('Got an malformed array')

        return array

    def find_subimage_in_array(self, sub_image, main_image, threshold=0.40, value=False, debug=False):
        """
        http://docs.opencv.org/3.1.0/d4/dc6/tutorial_py_template_matching.html

        Args:
            sub_image: A numby matrix containing the template we are trying to match
            main_image: A numpy array containing the main image we are trying to find the template in
            value: If true: Similarity is sent back.
            threshold: A treshhold regarding hos sensitive the matching should be.
        Returns:
            A list containing touples:
                If value is true:
                    The touples got he following elements(left,top,right,down,similarity)
                    Where similarity is a measure toward one
                Else:
                    The touples got he following elements(left,top,right,down)

        """
        # TODO: Check the test_init_wnd test for how to implement this :)
        logging.debug("Doing a template match with {} as threshold".format(threshold))
        methods = [cv2.TM_CCOEFF, cv2.TM_CCOEFF_NORMED, cv2.TM_CCORR, cv2.TM_CCORR_NORMED, cv2.TM_SQDIFF,
                   cv2.TM_SQDIFF_NORMED]
        method = methods[0]

        h, w = sub_image.shape[0:2]

        res = cv2.matchTemplate(main_image, sub_image, method)

        loc = np.where(res >= threshold)
        locations = []
        for pt in zip(*loc[::-1]):
            if value:
                locations.append((pt[0], pt[1], pt[0] + w, pt[1] + h, res[pt[1], pt[0]]))
            else:
                locations.append((pt[0], pt[1], pt[0] + w, pt[1] + h))

        logging.debug("Found {} locations".format(len(locations)))
        if debug:
            plt.subplot(121), plt.imshow(res, cmap='gray')
            plt.title('Matching Result'), plt.xticks([]), plt.yticks([])
            plt.subplot(122), plt.imshow(main_image, cmap='gray')
            plt.title('Detected Point'), plt.xticks([]), plt.yticks([])
            for pt in zip(*loc[::-1]):
                cv2.rectangle(main_image, pt, (pt[0] + w, pt[1] + h), (255, 0, 255), 2)
            plt.imshow(main_image)
            plt.show()

        if value:
            locations.sort(reverse=True, key=operator.itemgetter(4))
        return list(map(operator.itemgetter(0, 1, 2, 3), locations))

    def find_features_in_array_SIFT(self, sub_image, main_image, debug=False):
        # Initiate SIFT detector
        sift = SIFT_create()

        # find the keypoints and descriptors with SIFT
        kp1, des1 = sift.detectAndCompute(sub_image, None)
        kp2, des2 = sift.detectAndCompute(main_image, None)

        # BFMatcher with default params
        bf = cv2.BFMatcher()
        matches = bf.knnMatch(des1, des2, k=2)

        logging.debug("Found {} possible matches".format(len(matches)))

        ret_list = []
        good = []
        for m, n in matches:
            if m.distance < 0.75 * n.distance:
                good.append([m])

        good.sort(key=lambda x: x[0].distance)

        if debug:
            # cv2.drawMatchesKnn expects list of lists as matches.
            img3 = cv2.drawMatchesKnn(sub_image, kp1, main_image, kp2, good, flags=2, outImg=None,
                                      matchColor=(255, 255, 0))
            plt.imshow(img3), plt.show()

        ret_list = []
        for match in good:
            index = match[0].trainIdx
            point = kp2[index].pt
            ret_list.append((int(point[0]), int(point[1])))

        logging.debug("After filtering {}".format(len(good)))
        return ret_list

    def validate_clustering(self, sub_image, main_image, points, clusters=3, target_matches=10,
                            minimal_match_percent=0.8, debug=False):
        """
        This function takes in the main target picture (template) and the main image. The goal is to validate and return
        probable best location to press if there is probable the sub_image actually is present

        Args:
            minimal_matches: A minimal number of matches needed regardless of percentages
            match_percent: The needed percentage for a good match
            sub_image: The target image
            main_image: Where we are looking for the target
            points: A list of points returned from the find_features_in_array_SIFT()
            debug: Display the clustering found

        Returns:
            Returns a list of touples based on the following format:
                ((x,y),number of matches, percentages)
            A touple with the most probably (x,y) coord or None if no likely match found

        """

        if len(points) == 0:
            return None

        if len(points) < clusters:
            logging.debug("Fewer points than clusters found, aborting")
            # Maybe just try clustering with fewer clusters?
            return None

        points = numpy.asarray(points, dtype=np.float32)
        points: numpy.ndarray = numpy.float32(points)

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        ret, label, centers = cv2.kmeans(points, clusters, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)

        # TODO: Fix the Deprecation error here

        point_clusters = []
        for cluster in range(clusters + 1):
            point_clusters.append(points[label.ravel() == cluster])

        # Plot the data
        if debug:
            plt.imshow(main_image)
            for cluster_points in point_clusters:
                plt.scatter(cluster_points[:, 0], cluster_points[:, 1])
                plt.scatter(centers[:, 0], centers[:, 1], s=80, c='y', marker='s')
            plt.xlabel('Height'), plt.ylabel('Weight')
            plt.show()

        box_size = sub_image.shape[0:2]  # NOTE: X/Y is swapped in numpy

        center_stats = []

        for center in centers:
            center = center.astype(np.int32).tolist()
            center = tuple(center)

            left = int(center[0] - box_size[1] / 2)
            right = int(center[0] + box_size[1] / 2)

            top = int(center[1] - box_size[0] / 2)
            bottom = int(center[1] + box_size[0] / 2)

            out_img = main_image[:]
            # TODO: Optimize with numpy-vectorization
            box = (left, top, right, bottom)

            cv2.rectangle(out_img, (left, top), (right, bottom), (255, 0, 255), 5)

            matches = 0
            percentages = 0.0

            for point in points:
                point = point.astype(np.int32).tolist()
                point = tuple(point)

                vert_match = left <= point[0] <= right
                horiz_match = top <= point[1] <= bottom

                if vert_match and horiz_match:
                    matches = matches + 1
                    if debug:
                        out_img = cv2.circle(out_img, point, 5, color=(0, 255, 0), thickness=-1)
                else:
                    if debug:
                        out_img = cv2.circle(out_img, point, 5, color=(255, 255, 0), thickness=-1)

                percentages = matches / len(points)

            logging.debug("Had {} points in rect ({})".format(matches, percentages))

            if debug:
                plt.imshow(out_img)
                plt.show()

            if percentages <= minimal_match_percent or matches <= target_matches:
                logging.debug("Too small percentages or matches to pass")
                continue

            logging.debug("All cluster tests passed. Adding center {}".format(center))
            center_stats.append((center, target_matches, percentages))

        center_stats.sort(reverse=True, key=operator.itemgetter(2))
        logging.debug("Found {} centres".format(len(center_stats)))
        return center_stats

    # TODO: Click and drag version of this function
    def print_win_percentage_click(self, buttonEvent, x, y, scrollDelta, bbox):
        """
        This method is meant to work with the setMouseCallback funciton
        The button events can be found here:
        https://docs.opencv.org/3.1.0/d7/dfc/group__highgui.html#ga927593befdddc7e7013602bca9b079b0

        :param buttonEvent: What sort of mouseEvent has triggered. Check the link for enums
        :param x: X coord relative to the content of the show window
        :param y: Y coord relative to the content of the show window
        :param scrollDelta: Some jankyass delta that tells about the how much you have scrolled
        :param bbox: The bounding box of the window we want to do math on
        :return: a tuple with the percentage of the image clicked
        """

        # Getting the size of the window
        h = bbox[3] - bbox[1]
        w = bbox[2] - bbox[0]

        # TODO: Use some sort of pass by reference instead
        if buttonEvent == cv2.EVENT_LBUTTONDOWN:
            self.mouseEvent.pos_start = (x, y)
            self.mouseEvent.state = cv2.EVENT_LBUTTONDOWN
            self.mouseEvent.pos_stop = None
            self.mouseEvent.pos_box = None
        elif buttonEvent == cv2.EVENT_LBUTTONUP:
            self.mouseEvent.pos_stop = (x, y)
            self.mouseEvent.state = None
            self.mouseEvent.pos_box = (*self.mouseEvent.pos_start, *self.mouseEvent.pos_stop)
            print(self.coord_to_percent(bbox, self.mouseEvent.pos_start),
                  self.coord_to_percent(bbox, self.mouseEvent.pos_stop))

    @staticmethod
    def coord_to_percent(bbox, coord):
        h = bbox[3] - bbox[1]
        w = bbox[2] - bbox[0]
        return coord[0] / float(w), coord[1] / float(h)

    @staticmethod
    def percent_to_coord(bbox, percent_coord):
        h = bbox[3] - bbox[1]
        w = bbox[2] - bbox[0]
        return w * percent_coord[0], h * percent_coord[1]

    @staticmethod
    def coord_to_percent_box(bbox, coord):
        h = bbox[3] - bbox[1]
        w = bbox[2] - bbox[0]
        return coord[0] / float(w), \
               coord[1] / float(h), \
               coord[2] / float(w), \
               coord[3] / float(h)

    @staticmethod
    def percent_to_coord_box(bbox, percent_coord):
        h = bbox[3] - bbox[1]
        w = bbox[2] - bbox[0]
        return int(w * percent_coord[0]), \
               int(h * percent_coord[1]), \
               int(w * percent_coord[2]), \
               int(h * percent_coord[3])

    @staticmethod
    def aproximate_color_2d(target, found, shade):
        red = abs((found >> 16) - (target >> 16)) <= shade
        green = abs((found >> 8) & 0x0000FF - (target >> 8) & 0x0000FF) <= shade
        blue = abs(found & 0x0000FF - target & 0x0000FF) <= shade

        if red and green and blue:
            return 1
        return 0

    @staticmethod
    def aproximate_color_3d(array, color, shade):
        r = extract_color_band(color, 'R')
        g = extract_color_band(color, 'G')
        b = extract_color_band(color, 'B')

        numpy_array = abs(array[:, :, :] - (r, g, b)) <= shade
        return numpy_array

    @staticmethod
    def box_size(bbox):
        w, h = bbox[2] - bbox[0], bbox[1] - bbox[3]
        return w, h
