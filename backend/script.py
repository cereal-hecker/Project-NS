from sys import setrecursionlimit
from time import time
from base64 import b64encode
from skimage.io import imread, imshow
from skimage.transform import resize
import matplotlib.pyplot as plt
import cv2
from bisect import bisect_right
from keras import backend as K
from tensorflow.keras.models import load_model
import numpy as np
import firebase_admin
from firebase_admin import credentials, firestore

# CONSTANTS AND HELPER FUNCTIONS

setrecursionlimit((128*128) * 8)


def jacard_coef(y_true, y_pred):
    y_true_f = K.flatten(y_true)
    y_pred_f = K.flatten(y_pred)
    intersection = K.sum(y_true_f * y_pred_f)
    return (intersection + 1.0)/(K.sum(y_true_f)+K.sum(y_pred_f) - intersection + 1.0)


def jacard_coef_loss(y_true, y_pred):
    return -jacard_coef(y_true, y_pred)


def input_image(img):
    img = resize(img[:, :, :IMG_C], (IMG_H, IMG_W),
                 mode='constant', preserve_range=True)
    resized_frame[0] = img

    return resized_frame


IMG_H = 128
IMG_W = 128
IMG_C = 3

SIZE_OF_GRID = 128
_2Darray, visited = [], []


# INITIATION PHASE
cred = credentials.Certificate("./backend/serviceAccountKey.json")
model = load_model("./backend/UNET_BASE_MAXEPOCHS.h5", custom_objects={
                   'jacard_coef': jacard_coef})

app = firebase_admin.initialize_app(cred)
db = firestore.client()
# cap = cv2.VideoCapture(0)


resized_frame = np.zeros((1, IMG_H, IMG_W, IMG_C), dtype=np.uint8)


def dfs(i, j):
    """
        Here we are using a Depth-First Search, a graph traversal algorithm, 
        to count the number of connected components, thus letting us deduce the count of nuclei regions.
    """

    global pixel
    if i < 0 or j < 0 or i >= SIZE_OF_GRID or j >= SIZE_OF_GRID:
        return 0
    if visited[i][j] or not _2Darray[i][j]:
        return 0
    visited[i][j] = 1
    pixel += 1

    """
        We will be calling a DFS call for each direction from our current postition thus we traverse:
                               ^  ^  ^
                                \ | /
                              < - o - >
                                / | \ 
                               v  v  v
                                
            UP, DOWN, LEFT, RIGHT, UP-RIGHT, UP-LEFT, DOWN-RIGHT, DOWN-LEFT
    """
    for row, column in [(-1, 0), (1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (-1, 1), (1, -1)]:
        dfs(i+row, j+column)

def connectedCompenets():
    global pixel
    nuclei_count = 0
    pixels = []
    pixel = 0
    for i in range(SIZE_OF_GRID):
        for j in range(SIZE_OF_GRID):
            if _2Darray[i][j] and not visited[i][j]:
                nuclei_count += 1
                dfs(i, j)
                if pixel:
                    pixels.append(pixel)
                    pixel = 0
    pixels.sort()
    print(*pixels)

    Q1= np.percentile(pixels,25)
    Q2= np.percentile(pixels,50)
    Q3= np.percentile(pixels,75)

    IRQ = Q3 - Q1
    IRQ = IRQ*1.5

    up_idx = bisect_right(pixels, Q3)
    low_idx = bisect_right(pixels, Q1)

    out = pixels[low_idx : up_idx+1] 
    mean = sum(out) / max(1, len(out))

    adj_nuclei_count = up_idx + 1

    for i in range(up_idx+1, len(pixels)):
        adj_nuclei_count += pixels[i] / mean
    adj_nuclei_count = int(adj_nuclei_count)
    return nuclei_count, adj_nuclei_count

def save(nuclei_count=None, adj_nuclei_count=None, original_image=None):
    frame = cv2.imread("test.png", 1)
    _, jpeg = cv2.imencode('.png', frame)
    _, og_jpeg = cv2.imencode('.png', original_image)

    # Converting the image from a numpy array into jpeg-format
    # this image is encoded into Base64 format
    # we aren't using a storage bucket to store our images since
    # our images are small [128x128]
    # storing them into a NOSQL database is much efficent
    # Firestore's scalability is particularly good for our task at hand - high-volume of small data

    im_b64 = b64encode(jpeg.tobytes()).decode()
    ogim_b64 = b64encode(og_jpeg.tobytes()).decode()

    # Finally pushed into the database with an autogenerated ID
    # the ID-field is not significant for our use case
    if not(nuclei_count and adj_nuclei_count):
        nuclei_count, adj_nuclei_count = connectedCompenets()

    db.collection('Images').add({
        'segmented_image': im_b64,
        'original_image' : ogim_b64,
        'nuclei_count': nuclei_count,
        'adjusted_nuclei_count': adj_nuclei_count,
        'time': time()
    })

    print("Saved!")

while True:

    # _, frame = cap.read()
    frame = cv2.imread("backend/stage1_train/dd54adb80393de7769b9853c0aa2ee9b240905d0e99c59d4ccd99401f327aa05/images/dd54adb80393de7769b9853c0aa2ee9b240905d0e99c59d4ccd99401f327aa05.png")
    resized_frame = input_image(frame)
    segmented = model.predict(
        resized_frame[int(resized_frame.shape[0]*0.9):])
    visited = [[0 for _ in range(SIZE_OF_GRID)]
               for __ in range(SIZE_OF_GRID)]
    seg = np.squeeze((segmented > 0.56).astype(np.uint8))
    _2Darray = seg
    nuclei_count, adj_nuclei_count = connectedCompenets()

    print(nuclei_count, adj_nuclei_count)


    cv2.imshow("Window", frame)

    key = cv2.waitKey(1)

    if key == (ord('q')):
        break

    elif key == ord('f'):
        imshow(seg)
        plt.show()
        plt.savefig("test.png")
        choice = input("Enter 's' to save the segment to the database, else press 'Enter': ")
        if choice == 's':
            save(nuclei_count, adj_nuclei_count, frame)

    elif key == (ord('s')):
        imshow(seg)
        plt.savefig("test.png")
        save(nuclei_count, adj_nuclei_count, frame)

cv2.destroyAllWindows()
# cap.release()
