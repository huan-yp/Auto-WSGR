import os
import subprocess
from typing import List, Tuple

import cv2
import easyocr
from thefuzz import process

from autowsgr.constants.data_roots import TUNNEL_ROOT


class OCRBackend:
    WORD_REPLACE = None  # 记录中文ocr识别的错误用于替换。主要针对词表缺失的情况，会导致稳定的识别为另一个字

    def read_text(self, img, allowlist: List[str] = None, sort: str = "left-to-right"):
        """识别文字的具体实现，返回字符串格式识别结果"""
        raise NotImplementedError

    def recognize(
        self,
        img,
        allowlist: List[str] = None,
        candidates: List[str] = None,
        multiple=False,
    ):
        """识别任意字符串"""

        def process_text(t):
            for k, v in self.WORD_REPLACE.items():
                t = t.replace(k, v)
            if candidates:
                t = process.extractOne(t, candidates)[0]
            return t

        results = self.read_text(img, allowlist)
        results = [(t[0], process_text(t[1]), t[2]) for t in results]
        print(f"修正OCR结果：{results}")

        if multiple:
            return results
        else:
            assert len(results) == 1
            return results[0]

    def recognize_number(self, img, extra_chars="", multiple=False):
        """识别数字"""

        def process_number(t: str):
            # 决战，费用是f"x{cost}"格式
            if t.startswith("x"):
                return eval(t[1:])
            # 资源可以是K/M结尾
            if t.endswith("K"):
                return eval(t[:-1]) * 1000
            if t.endswith("M"):
                return eval(t[:-1]) * 1000000
            # 普通数字
            return eval(t)

        results = self.recognize(img, allowlist="0123456789" + extra_chars, multiple=True)
        results = [(t[0], process_number(t[1]), t[2]) for t in results]
        print(f"数字解析结果：{results}")

        if multiple:
            return results
        else:
            assert len(results) == 1
            return results[0]

    def recognize_ship(self, image, candidates):
        """传入一张图片,返回舰船信息,包括名字和舰船型号"""
        if isinstance(image, str):
            image_path = os.path.abspath(image)
        else:
            image_path = os.path.join(TUNNEL_ROOT, "OCR.PNG")
            cv2.imwrite(image_path, image)
        with open(os.path.join(TUNNEL_ROOT, "locator.in"), "w+") as f:
            f.write(image_path)
        locator_exe = os.path.join(TUNNEL_ROOT, "locator.exe")
        subprocess.run([locator_exe, TUNNEL_ROOT])
        if os.path.exists(os.path.join(TUNNEL_ROOT, "1.PNG")):
            img_path = os.path.join(TUNNEL_ROOT, "1.PNG")
        else:
            img_path = "1.PNG"
        return self.recognize(img_path, candidates=candidates, multiple=True)

    # def recognize_time(self, img, format="%H:%M:%S"):
    #     """识别时间"""
    #     text = self.recognize(img, allowlist="0123456789:").replace(" ", "")
    #     return str2time(text, format)


class EasyocrBackend(OCRBackend):
    WORD_REPLACE = {
        "鲍鱼": "鲃鱼",
    }

    def __init__(self) -> None:
        self.reader = easyocr.Reader(["ch_sim", "en"])

    def read_text(self, img, allowlist: List[str] = None, sort="left-to-right"):
        """识别文字的具体实现，返回字符串格式识别结果"""

        def get_center(pos1, pos2):
            x1, y1 = pos1
            x2, y2 = pos2
            return (x1 + x2) / 2, (y1 + y2) / 2

        results = self.reader.readtext(
            img,
            allowlist=allowlist,
            # TODO：以下参数可能需要调整，以获得最好OCR性能
            min_size=7,
            text_threshold=0.25,
            low_text=0.3,
        )
        results = [(get_center(r[0][0], r[0][2]), r[1], r[2]) for r in results]

        if sort == "left-to-right":
            results = sorted(results, key=lambda x: x[0][0])
        elif sort == "top-to-bottom":
            results = sorted(results, key=lambda x: x[0][1])
        else:
            raise ValueError(f"Invalid sort method: {sort}")

        print(f"原始OCR结果: {results}")
        return results
