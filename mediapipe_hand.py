import cv2
import mediapipe as mp

import time
from pathlib import Path

CAMERA_INDEX = 0
MODEL_PATH = "C:/Users/User/Desktop/hand_landmarker.task"
CONNECTIONS = mp.tasks.vision.HandLandmarksConnections.HAND_CONNECTIONS

def draw_hand(frame, hand):
    height, width = frame.shape[:2]
    points = []

    for landmark in hand:
        x = int(landmark.x * width)
        y = int(landmark.y * height)
        points.append((x,y))

    for line in CONNECTIONS:
        cv2.line(frame, points[line.start], points[line.end], (0,220,255), 2)

    for point in points:
        cv2.circle(frame, point, 5, (0,70,255), -1)



camera = cv2.VideoCapture(CAMERA_INDEX)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

if not camera.isOpened():
    raise RuntimeError("Camera open failed")

print("Camera started")

options = mp.tasks.vision.HandLandmarkerOptions(base_options = mp.tasks.BaseOptions(model_asset_path = str(MODEL_PATH)),
                                                running_mode = mp.tasks.vision.RunningMode.VIDEO,
                                                num_hands = 1,
                                                )

with mp.tasks.vision.HandLandmarker.create_from_options(options) as detector:
    while True:
        success, frame = camera.read()

        if not success:
            print("Camera read failed")
            break

        frame = cv2.flip(frame, 1)

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(mp.ImageFormat.SRGB, rgb_frame)
        timestamp_ms = int(time.monotonic() * 1000)
        result = detector.detect_for_video(mp_image, timestamp_ms)

        if result.hand_landmarks:
           hand = result.hand_landmarks[0]
           draw_hand(frame, hand)

        cv2.imshow("camera", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

camera.release()
cv2.destroyAllWindows()
