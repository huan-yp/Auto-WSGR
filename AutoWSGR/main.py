import os

import keyboard as kd
import yaml

from AutoWSGR.constants.settings import S
from AutoWSGR.controller.run_timer import Timer
from AutoWSGR.utils.debug import print_debug
from AutoWSGR.utils.io import recursive_dict_update, yaml_to_dict

event_pressed = set()
script_end = 0
print_debug(S.DEBUG, "main is imported")


def lencmp(s1, s2):
    if (len(s1) < len(s2)):
        return 1
    if (len(s1) > len(s2)):
        return -1
    return 0


def listener(event: kd.KeyboardEvent):
    on_press = event_pressed
    if (event.event_type == 'down'):
        if (event.name in on_press):
            return
        on_press.add(event.name)
    if (event.event_type == 'up'):
        on_press.discard(event.name)

    if ('ctrl' in on_press and 'alt' in on_press and 'c' in on_press):
        global script_end
        script_end = 1
        print("Script end by user request")
        quit()


def start_script(settings_path=None, to_main_page=True):
    """启动脚本,返回一个 Timer 记录器

    Returns:
        Timer: 该模拟器的记录器
    """
    config = yaml_to_dict(os.path.join(os.path.dirname(__file__), "data", "default_settings.yaml"))
        
    if settings_path is not None:
        user_settings = yaml_to_dict(settings_path)
        config = recursive_dict_update(config, user_settings)
    
    timer = Timer(config)
    timer.setup(to_main_page)

    return timer
