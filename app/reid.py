import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import os
import argparse
import multiprocessing
import numpy as np
import setproctitle
import cv2
import time
import hailo
from hailo_rpi_common import (
    get_default_parser,
    QUEUE,
    get_caps_from_pad,
    get_numpy_from_buffer,
    GStreamerApp,
    app_callback_class,
)

# -----------------------------------------------------------------------------------------------
# User-defined class to be used in the callback function
# -----------------------------------------------------------------------------------------------
# Inheritance from the app_callback_class
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()
        self.new_variable = 42  # New variable example
    
    def new_function(self):  # New function example
        return "The meaning of life is: "

# -----------------------------------------------------------------------------------------------
# User-defined callback function
# -----------------------------------------------------------------------------------------------

# This is the callback function that will be called when data is available from the pipeline
def app_callback(pad, info, user_data):
    # # Get the GstBuffer from the probe info
    # buffer = info.get_buffer()
    # # Check if the buffer is valid
    # if buffer is None:
    #     return Gst.PadProbeReturn.OK
        
    # # Using the user_data to count the number of frames
    # user_data.increment()
    # string_to_print = f"Frame count: {user_data.get_count()}\n"
    
    # # Get the detections from the buffer
    # roi = hailo.get_roi_from_buffer(buffer)
    # detections = roi.get_objects_typed(hailo.HAILO_DETECTION)
    
    # #import ipdb; ipdb.set_trace()
    # # Parse the detections
    # detection_count = 0
    # for detection in detections:
    #     label = detection.get_label()
    #     bbox = detection.get_bbox()
    #     confidence = detection.get_confidence()
    #     string_to_print += f"Detection: {label} {confidence:.2f}\n"
    #     detection_count += 1
    # print(string_to_print)
    return Gst.PadProbeReturn.OK
    

# -----------------------------------------------------------------------------------------------
# User Gstreamer Application
# -----------------------------------------------------------------------------------------------

# This class inherits from the hailo_rpi_common.GStreamerApp class
class GStreamerDetectionApp(GStreamerApp):
    def __init__(self, args, user_data):
        # Call the parent class constructor
        super().__init__(args, user_data)
        # Additional initialization code can be added here
        # Set Hailo parameters these parameters should be set based on the model used
        self.batch_size = 4
        self.network_width = 640
        self.network_height = 640
        self.network_format = "RGB"
        
        self.SCRIPT_PATH = os.path.realpath(__file__)
        self.SCRIPT_DIR = os.path.dirname(self.SCRIPT_PATH)
        self.RESOURCES_DIR = os.path.join(self.SCRIPT_DIR, "resources")
        self.POSTPROCESS_DIR = os.path.join(os.getenv('TAPPAS_WORKSPACE'), "apps/h8/gstreamer/libs/post_processes/")
        self.APPS_LIBS_DIR = os.path.join(os.getenv('TAPPAS_WORKSPACE'), "apps/h8/gstreamer/libs/apps/re_id/")
        self.POSTPROCESS_SO = os.path.join(self.POSTPROCESS_DIR, "libyolo_post.so")
        self.CROPPER_SO = os.path.join(self.POSTPROCESS_DIR, "cropping_algorithms/libre_id.so")
        self.RE_ID_POST_SO = os.path.join(self.POSTPROCESS_DIR, "libre_id.so")
        self.RE_ID_DEWARP_SO = os.path.join(self.APPS_LIBS_DIR, "libre_id_dewarp.so")
        self.HEF_PATH = os.path.join(self.RESOURCES_DIR, "yolov5s_personface_reid.hef")
        self.REID_HEF_PATH = os.path.join(self.RESOURCES_DIR, "repvgg_a0_person_reid_2048.hef")
        self.FUNCTION_NAME = "yolov5_personface_letterbox"
        self.RE_ID_OVERLAY = os.path.join(self.APPS_LIBS_DIR, "libre_id_overlay.so")
        self.DEFAULT_JSON_CONFIG_PATH = os.path.join(self.RESOURCES_DIR, "configs/yolov5_personface.json")
        self.WHOLE_BUFFER_CROP_SO = os.path.join(self.POSTPROCESS_DIR, "cropping_algorithms/libwhole_buffer.so")
        self.SRC_0 = "rtsp://root:hailo@192.168.241.62:554/axis-media/media.amp"
        self.SRC_1 = "rtsp://root:hailo@192.168.241.63:554/axis-media/media.amp"
        self.SRC_2 = "rtsp://root:hailo@192.168.241.64:554/axis-media/media.amp"
        self.SRC_3 = "rtsp://root:hailo@192.168.241.65:554/axis-media/media.amp"
        self.video_sink_element = "xvimagesink"
        #self.video_sink = f"fpsdisplaysink video-sink={self.video_sink_element} text-overlay=false"
        self.num_of_src = 4
        self.additional_parameters = ""
        self.sources = ""
        # self.compositor_locations = "sink_0::xpos=0 sink_0::ypos=0 sink_1::xpos=800 sink_1::ypos=0 sink_2::xpos=0 sink_2::ypos=450 sink_3::xpos=800 sink_3::ypos=450"
        # set for 640x360
        self.compositor_locations = "sink_0::xpos=0 sink_0::ypos=0 sink_1::xpos=640 sink_1::ypos=0 sink_2::xpos=0 sink_2::ypos=360 sink_3::xpos=640 sink_3::ypos=360"
        self.print_gst_launch_only = False
        self.vdevice_key = 1
        self.json_config_path = self.DEFAULT_JSON_CONFIG_PATH
        self.dewarp_element = ""
        self.source_prefix = "reid"

        self.app_callback = app_callback
        # Set the process title
        setproctitle.setproctitle("Hailo Detection App")

        self.create_pipeline()

    def create_sources(self):
        sources = ""
        streamrouter_input_streams = ""
        for n in range(self.num_of_src):
            src_name = eval(f"self.SRC_{n}")
            sources += (f"rtspsrc location={src_name} name=source_{n} message-forward=true ! "
                        + "rtph264depay ! "
                        + QUEUE(f"hailo_decode_q_{n}")
                        + "decodebin ! "
                        + QUEUE(f"hailo_scale_q_{n}", leaky="downstream")
                        + "videoscale n-threads=4 ! "
                        + QUEUE(f"hailo_convert_q_{n}")
                        + "videoconvert n-threads=4 ! "
                        + "video/x-raw,pixel-aspect-ratio=1/1,format=RGB ! "
                        + QUEUE(f"hailo_rr_q_{n}")
                        + f"fun.sink_{n} sid.src_{n} ! "
                        + QUEUE(f"hailo_sid_scale_q_{n}") +
                        "videoscale add-borders=false qos=false ! video/x-raw, width=640, height=360, pixel-aspect-ratio=1/1 ! "
                        + QUEUE(f"comp_q_{n}")
                        + f"comp.sink_{n} "
                        )
            streamrouter_input_streams += f" src_{n}::input-streams=\"<sink_{n}>\""
        self.sources = sources
        self.streamrouter_input_streams = streamrouter_input_streams
        
    def get_pipeline_string(self):
        self.create_sources()
        RE_ID_PIPELINE = (
            QUEUE(f"hailo_pre_cropper2_q") +
            f"hailocropper so-path={self.CROPPER_SO} function-name=create_crops internal-offset=true name=cropper2 "
            f"hailoaggregator name=agg2 "
            f"cropper2. ! " + QUEUE(f"bypass2_q",max_size_buffers=30) + "agg2. "
            f"cropper2. ! " + QUEUE(f"pre_reid_q") +
            f"hailonet hef-path={self.REID_HEF_PATH} scheduling-algorithm=1 vdevice-key={self.vdevice_key} batch_size={self.batch_size} ! "
            + QUEUE(f"reid_post_q") +
            f"hailofilter so-path={self.RE_ID_POST_SO} qos=false ! "
            + QUEUE(f"reid_pre_agg_q") + "agg2. agg2. ! "
        )

        DETECTION_PIPELINE = (
            QUEUE(f"hailo_pre_cropper1_q") +
            f"hailocropper so-path={self.WHOLE_BUFFER_CROP_SO} function-name=create_crops use-letterbox=true resize-method=inter-area internal-offset=true name=cropper1 "
            f"hailoaggregator name=agg1 "
            f"cropper1. ! " + QUEUE(f"bypass1_q",max_size_buffers=30) + "agg1. "
            f"cropper1. ! " + QUEUE(f"hailo_pre_detector_q") +
            "identity name=identity_callback ! "
            + QUEUE(f"hailo_identity_q") +
            f"hailonet hef-path={self.HEF_PATH} scheduling-algorithm=1 vdevice-key={self.vdevice_key} batch_size={self.batch_size} ! "
            + QUEUE(f"detector_post_q") +
            f"hailofilter so-path={self.POSTPROCESS_SO} qos=false function_name={self.FUNCTION_NAME} config-path={self.json_config_path} ! "
            + QUEUE(f"detector_pre_agg_q") + 
            "agg1. agg1. ! "
        )

        pipeline_string = ("hailoroundrobin mode=2 name=fun ! "
            + QUEUE(f"hailo_pre_convert_0") +
            "videoconvert n-threads=4 qos=false ! video/x-raw,format=RGB ! "
            f"{DETECTION_PIPELINE} "
            + QUEUE(f"hailo_pre_tracker") +
            "hailotracker name=hailo_tracker hailo-objects-blacklist=hailo_landmarks,hailo_depth_mask,hailo_class_mask,hailo_matrix "
            "class-id=1 kalman-dist-thr=0.7 iou-thr=0.7 init-iou-thr=0.8 keep-new-frames=2 keep-tracked-frames=4 "
            "keep-lost-frames=8 qos=false std-weight-position-box=0.01 std-weight-velocity-box=0.001 ! "
            f"{RE_ID_PIPELINE} "
            + QUEUE(f"hailo_pre_gallery") +
            "hailogallery similarity-thr=.2 gallery-queue-size=100 class-id=1 ! "
            + QUEUE(f"hailo_pre_draw") +
            f"hailofilter use-gst-buffer=true so-path={self.RE_ID_OVERLAY} qos=false ! "
            + QUEUE(f"hailo_post_draw") +
            "videoconvert n-threads=4 qos=false ! "
            f"hailostreamrouter name=sid {self.streamrouter_input_streams} "
            f"compositor name=comp start-time-selection=0 {self.compositor_locations} ! "
            + QUEUE(f"hailo_display_q") +
            f"fpsdisplaysink video-sink={self.video_sink_element} name=hailo_display sync={self.sync} text-overlay={self.options_menu.show_fps} signal-fps-measurements=true max-lateness=-1 qos=false "
            f"{self.sources} "
        )
        print(pipeline_string)
        return pipeline_string

if __name__ == "__main__":
    # Create an instance of the user app callback class
    user_data = user_app_callback_class()
    parser = get_default_parser()
    # Add additional arguments here
    args = parser.parse_args()
    app = GStreamerDetectionApp(args, user_data)
    app.run()
