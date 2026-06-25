import sys
sys.path.insert(0, '.')

# Force model load karo
from insightface.app import FaceAnalysis
import os

model_name = 'buffalo_l'
print(f"Loading {model_name}...")

app = FaceAnalysis(name=model_name, providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=(640,640))

print("Model loaded! Testing...")

import cv2
import numpy as np

# Test frame
frame = np.zeros((480,640,3), dtype=np.uint8)
faces = app.get(frame)
print(f"Test OK - detected {len(faces)} faces on blank frame")

# Ab backend core mein inject karo
import backend.core.ai_pipeline as pipeline
pipeline._app = app
pipeline._model_ready = True
print(f"Pipeline ready: {pipeline.is_model_ready()}")