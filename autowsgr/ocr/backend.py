import datetime
from typing import List

import easyocr
from thefuzz import process

from autowsgr.utils.time import str2time


class OCRBackend:
    WORD_REPLACE = None  # 记录中文ocr识别的错误用于替换。主要针对词表缺失的情况，会导致稳定的识别为另一个字

    def read_text(self, img, allowlist: List[str] = None) -> str:
        """识别文字的具体实现，返回字符串格式识别结果"""
        raise NotImplementedError

    def recognize(self, img, allowlist: List[str] = None, candidates: List[str] = None, multiple=False):
        """识别任意字符串"""

        def process_text(t):
            for k, v in self.WORD_REPLACE.items():
                t = t.replace(k, v)
            if candidates:
                t = process.extractOne(t, candidates)[0]
            return t

        text = [process_text(t) for t in self.read_text(img, allowlist)]
        print(f"修正OCR结果：{text}")

        if multiple:
            return text
        else:
            return "".join(text)

    def recognize_number(self, img, multiple=False):
        """识别数字"""

        def process_number(t: str):
            # 决战，费用是f"x{cost}"格式
            if t.startswith("x") or t.startswith("X"):
                return eval(t[1:])
            # 资源可以是K/M结尾
            if t.endswith("K"):
                return eval(t[:-1]) * 1000
            if t.endswith("M"):
                return eval(t[:-1]) * 1000000
            # 普通数字
            return eval(t)

        nums = [process_number(t) for t in self.recognize(img, allowlist="xX0123456789.KM", multiple=True)]
        print(f"数字解析结果：{nums}")

        if multiple:
            return nums
        else:
            assert len(nums) == 1
            return nums[0]

    def recognize_time(self, img, format="%H:%M:%S"):
        """识别时间"""
        text = self.recognize(img, allowlist="0123456789:").replace(" ", "")
        return str2time(text, format)


class EasyocrBackend(OCRBackend):
    WORD_REPLACE = {
        "鲍鱼": "鲃鱼",
    }

    def __init__(self) -> None:
        self.reader = easyocr.Reader(["ch_sim", "en"])

    def read_text(self, img, allowlist: List[str] = None):
        results = self.reader.readtext(
            img,
            allowlist=allowlist,
            text_threshold=0.55,  # TODO：调参，有识别不出情况
            low_text=0.3,
        )
        results = [(r[1], r[2]) for r in results]
        print(f"原始OCR结果: {results}")

        return [r[0] for r in results]
