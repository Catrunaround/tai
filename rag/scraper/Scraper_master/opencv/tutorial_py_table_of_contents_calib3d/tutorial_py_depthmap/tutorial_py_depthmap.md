
# Goal

In this session,

* We will learn to create a depth map from stereo images.

# Basics

In the last session, we saw basic concepts like epipolar constraints and other related terms. We also saw that if we have two images of same scene, we can get depth information from that in an intuitive way. Below is an image and some simple mathematical formulas which prove that intuition. (Image Courtesy :

![](../../stereo_depth.jpg)

image
The above diagram contains equivalent triangles. Writing their equivalent equations will yield us following result:

\[disparity = x - x' = \frac{Bf}{Z}\]

\(x\) and \(x'\) are the distance between points in image plane corresponding to the scene point 3D and their camera center. \(B\) is the distance between two cameras (which we know) and \(f\) is the focal length of camera (already known). So in short, the above equation says that the depth of a point in a scene is inversely proportional to the difference in distance of corresponding image points and their camera centers. So with this information, we can derive the depth of all pixels in an image.

So it finds corresponding matches between two images. We have already seen how epiline constraint make this operation faster and accurate. Once it finds matches, it finds the disparity. Let's see how we can do it with OpenCV.

# Code

Below code snippet shows a simple procedure to create a disparity map. 

import numpy as np
import cv2 as cv
from matplotlib import pyplot as plt

imgL = [cv.imread](../../d4/da8/group__imgcodecs.html#gab32ee19e22660912565f8140d0f675a8 "../../d4/da8/group__imgcodecs.html#gab32ee19e22660912565f8140d0f675a8")('tsukuba\_l.png', cv.IMREAD\_GRAYSCALE)
imgR = [cv.imread](../../d4/da8/group__imgcodecs.html#gab32ee19e22660912565f8140d0f675a8 "../../d4/da8/group__imgcodecs.html#gab32ee19e22660912565f8140d0f675a8")('tsukuba\_r.png', cv.IMREAD\_GRAYSCALE)

stereo = [cv.StereoBM.create](../../d9/dba/classcv_1_1StereoBM.html#a119436b6cb382e0895dd0fa58229ec17 "../../d9/dba/classcv_1_1StereoBM.html#a119436b6cb382e0895dd0fa58229ec17")(numDisparities=16, blockSize=15)
disparity = stereo.compute(imgL,imgR)
plt.imshow(disparity,'gray')
plt.show()
[cv::StereoBM::create](../../d9/dba/classcv_1_1StereoBM.html#a119436b6cb382e0895dd0fa58229ec17 "../../d9/dba/classcv_1_1StereoBM.html#a119436b6cb382e0895dd0fa58229ec17")static Ptr< StereoBM > create(int numDisparities=0, int blockSize=21)Creates StereoBM object.
[cv::imread](../../d4/da8/group__imgcodecs.html#gab32ee19e22660912565f8140d0f675a8 "../../d4/da8/group__imgcodecs.html#gab32ee19e22660912565f8140d0f675a8")CV\_EXPORTS\_W Mat imread(const String &filename, int flags=IMREAD\_COLOR)Loads an image from a file.
 Below image contains the original image (left) and its disparity map (right). As you can see, the result is contaminated with high degree of noise. By adjusting the values of numDisparities and blockSize, you can get a better result.

![](../../disparity_map.jpg)

image
There are some parameters when you get familiar with StereoBM, and you may need to fine tune the parameters to get better and smooth results. Parameters:

* texture\_threshold: filters out areas that don't have enough texture for reliable matching
* Speckle range and size: Block-based matchers often produce "speckles" near the boundaries of objects, where the matching window catches the foreground on one side and the background on the other. In this scene it appears that the matcher is also finding small spurious matches in the projected texture on the table. To get rid of these artifacts we post-process the disparity image with a speckle filter controlled by the speckle\_size and speckle\_range parameters. speckle\_size is the number of pixels below which a disparity blob is dismissed as "speckle." speckle\_range controls how close in value disparities must be to be considered part of the same blob.
* Number of disparities: How many pixels to slide the window over. The larger it is, the larger the range of visible depths, but more computation is required.
* min\_disparity: the offset from the x-position of the left pixel at which to begin searching.
* uniqueness\_ratio: Another post-filtering step. If the best matching disparity is not sufficiently better than every other disparity in the search range, the pixel is filtered out. You can try tweaking this if texture\_threshold and the speckle filtering are still letting through spurious matches.
* prefilter\_size and prefilter\_cap: The pre-filtering phase, which normalizes image brightness and enhances texture in preparation for block matching. Normally you should not need to adjust these.

These parameters are set with dedicated setters and getters after the algoritm initialization, such as `setTextureThreshold`, `setSpeckleRange`, `setUniquenessRatio`, and more. See [cv::StereoBM](../../d9/dba/classcv_1_1StereoBM.html "Class for computing stereo correspondence using the block matching algorithm, introduced and contribu...") documentation for details.

# Additional Resources

* [Ros stereo img processing wiki page](http://wiki.ros.org/stereo_image_proc/Tutorials/ChoosingGoodStereoParameters "http://wiki.ros.org/stereo_image_proc/Tutorials/ChoosingGoodStereoParameters")

# Exercises

1. OpenCV samples contain an example of generating disparity map and its 3D reconstruction. Check stereo\_match.py in OpenCV-Python samples.
