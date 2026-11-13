"""개발용: inaSpeechSegmenter의 speech/music/noise Keras 모델을 ONNX로 변환한다.
배포판에는 포함하지 않는다 (TensorFlow 필요)."""
import os, sys
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import tensorflow as tf
from tensorflow import keras
import tf2onnx

src = os.path.expanduser(r"~\.keras\inaSpeechSegmenter\keras_speech_music_noise_cnn.hdf5")
dst = os.path.join(os.path.dirname(__file__), "..", "engine", "models", "speech_music_noise.onnx")
model = keras.models.load_model(src, compile=False)

@tf.function(input_signature=[tf.TensorSpec([None, 68, 21, 1], tf.float32, name="patches")])
def infer(x):
    return model(x, training=False)

tf2onnx.convert.from_function(infer, input_signature=infer.input_signature, opset=17, output_path=dst)
print("saved", os.path.abspath(dst), os.path.getsize(dst))
