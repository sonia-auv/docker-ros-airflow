# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

r"""Convert the Oxford pet dataset to TFRecord for object_detection.
See: O. M. Parkhi, A. Vedaldi, A. Zisserman, C. V. Jawahar
     Cats and Dogs
     IEEE Conference on Computer Vision and Pattern Recognition, 2012
     http://www.robots.ox.ac.uk/~vgg/data/pets/
Example usage:
    ./create_pet_tf_record --data_dir=/home/user/pet \
        --output_dir=/home/user/pet/output
"""
import argparse
import hashlib
import io
import logging
import os
import random
import re
import shutil

from lxml import etree
import PIL.Image
import tensorflow as tf

from object_detection.utils import dataset_util
from object_detection.utils import label_map_util


FLAGS = None


def dict_to_tf_example(data, label_map_dict, image_subdirectory, ignore_difficult_instances=False):
    """Convert XML derived dict to tf.Example proto.
    Notice that this function normalizes the bounding box coordinates provided
    by the raw data.
    Args:
      data: dict holding PASCAL XML fields for a single image (obtained by
        running dataset_util.recursive_parse_xml_to_dict)
      label_map_dict: A map from string label names to integers ids.
      image_subdirectory: String specifying subdirectory within the
        Pascal dataset directory holding the actual image data.
      ignore_difficult_instances: Whether to skip difficult instances in the
        dataset  (default: False).
    Returns:
      example: The converted tf.Example.
    Raises:
      ValueError: if the image pointed to by data['filename'] is not a valid JPEG
    """
    img_path = os.path.join(image_subdirectory, data["filename"])
    with tf.gfile.GFile(img_path, "rb") as fid:
        encoded_jpg = fid.read()
    encoded_jpg_io = io.BytesIO(encoded_jpg)
    image = PIL.Image.open(encoded_jpg_io)
    if image.format != "JPEG":
        raise ValueError("Image format not JPEG")
    key = hashlib.sha256(encoded_jpg).hexdigest()

    width = int(data["size"]["width"])
    height = int(data["size"]["height"])

    xmin = []
    ymin = []
    xmax = []
    ymax = []
    classes = []
    classes_text = []
    truncated = []
    poses = []
    difficult_obj = []
    try:
        for obj in data["object"]:
            difficult_obj.append(int(0))

            xmin.append(float(obj["bndbox"]["xmin"]) / width)
            ymin.append(float(obj["bndbox"]["ymin"]) / height)
            xmax.append(float(obj["bndbox"]["xmax"]) / width)
            ymax.append(float(obj["bndbox"]["ymax"]) / height)

            class_name = obj["name"]
            classes_text.append(class_name.encode("utf8"))
            classes.append(label_map_dict[class_name])
            truncated.append(int(0))
            poses.append("Unspecified".encode("utf8"))
    except KeyError as e:
        print(img_path)
        return None

    example = tf.train.Example(
        features=tf.train.Features(
            feature={
                "image/height": dataset_util.int64_feature(height),
                "image/width": dataset_util.int64_feature(width),
                "image/filename": dataset_util.bytes_feature(data["filename"].encode("utf8")),
                "image/source_id": dataset_util.bytes_feature(data["filename"].encode("utf8")),
                "image/key/sha256": dataset_util.bytes_feature(key.encode("utf8")),
                "image/encoded": dataset_util.bytes_feature(encoded_jpg),
                "image/format": dataset_util.bytes_feature("jpeg".encode("utf8")),
                "image/object/bbox/xmin": dataset_util.float_list_feature(xmin),
                "image/object/bbox/xmax": dataset_util.float_list_feature(xmax),
                "image/object/bbox/ymin": dataset_util.float_list_feature(ymin),
                "image/object/bbox/ymax": dataset_util.float_list_feature(ymax),
                "image/object/class/text": dataset_util.bytes_list_feature(classes_text),
                "image/object/class/label": dataset_util.int64_list_feature(classes),
                "image/object/difficult": dataset_util.int64_list_feature(difficult_obj),
                "image/object/truncated": dataset_util.int64_list_feature(truncated),
                "image/object/view": dataset_util.bytes_list_feature(poses),
            }
        )
    )
    return example


def create_tf_record(output_filename, label_map_dict, annotations_dir, image_dir, examples):
    """Creates a TFRecord file from examples.
    Args:
      output_filename: Path to where output file is saved.
      label_map_dict: The label map dictionary.
      annotations_dir: Directory where annotation files are stored.
      image_dir: Directory where image files are stored.
      examples: Examples to parse and save to tf record.
    """
    writer = tf.io.TFRecordWriter(output_filename)
    for idx, example in enumerate(examples):
        if idx % 100 == 0:
            logging.info("On image %d of %d", idx, len(examples))
        path = os.path.join(annotations_dir, example + ".xml")

        if not os.path.exists(path):
            logging.warning("Could not find %s, ignoring example.", path)
            continue
        with tf.gfile.GFile(path, "r") as fid:
            xml_str = fid.read()
        xml = etree.fromstring(xml_str)
        data = dataset_util.recursive_parse_xml_to_dict(xml)["annotation"]

        tf_example = dict_to_tf_example(data, label_map_dict, image_dir)

        if tf_example != None:
            writer.write(tf_example.SerializeToString())
    writer.close()
    logging.info(f"TF Record generated in{os.path.exists(output_filename)}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--label_map_file", type=str, required=True, help="Path to label_map.pbtxt file."
    )
    parser.add_argument("--image_dir", type=str, required=True, help="Path to images directory.")
    parser.add_argument(
        "--annotation_dir", type=str, required=True, help="Path to annotation directory."
    )
    parser.add_argument(
        "--trainval_file", type=str, required=True, help="Path to trainval.txt file."
    )
    parser.add_argument("--output_dir", type=str, required=True, help="Path to output directory.")

    return parser


def main(_):
    home = os.path.expanduser("~")

    label_map_dict = label_map_util.get_label_map_dict(FLAGS.label_map_file)

    logging.info("Reading from dataset.")
    image_dir = FLAGS.image_dir
    annotations_dir = FLAGS.annotation_dir
    output_dir = FLAGS.output_dir
    examples_path = FLAGS.trainval_file
    examples_list = dataset_util.read_examples_list(examples_path)

    # Test images are not included in the downloaded data set, so we shall perform
    # our own split.
    random.seed(42)
    random.shuffle(examples_list)
    num_examples = len(examples_list)
    num_train = int(0.95 * num_examples)
    train_examples = examples_list[:num_train]
    val_examples = examples_list[num_train:]
    logging.info("%d training and %d validation examples.", len(train_examples), len(val_examples))

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    train_output_path = os.path.join(output_dir, "train.record")
    val_output_path = os.path.join(output_dir, "val.record")
    label_map_output_path = os.path.join(output_dir, "label_map.pbtxt")
    create_tf_record(train_output_path, label_map_dict, annotations_dir, image_dir, train_examples)
    create_tf_record(val_output_path, label_map_dict, annotations_dir, image_dir, val_examples)

    shutil.copy(FLAGS.label_map_file, label_map_output_path)


if __name__ == "__main__":
    parser = parse_args()
    FLAGS, unparsed = parser.parse_known_args()
    tf.compat.v1.app.run(main=main)
