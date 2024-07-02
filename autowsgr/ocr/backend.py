import datetime
from typing import List

import easyocr
from thefuzz import process

from autowsgr.utils.time import str2time


class OCRBackend:
    WORD_REPLACE = None  # 记录中文ocr识别的错误用于替换。主要针对词表缺失的情况，会导致稳定的识别为另一个字

    def _readtext(self, img, allowlist: List[str] = None, paragraph=True) -> str:
        """识别文字的具体实现，返回字符串格式识别结果"""
        raise NotImplementedError

    def recognize(self, img, allowlist: List[str] = None, candidates: List[str] = None):
        """识别任意字符串"""
        text = self._readtext(img, allowlist)
        # 进行通用替换
        for k, v in self.WORD_REPLACE.items():
            text = text.replace(k, v)
        # 最近邻搜索
        if candidates:
            text = process.extractOne(text, candidates)[0]
        return text

    def recognize_number(self, img):
        """识别单个数字"""
        text = self.recognize(img, allowlist="x0123456789.KM").replace(" ", "")
        # 决战，费用是f"x{cost}"格式
        if text.startswith("x"):
            return eval(text[1:])
        # 资源可以是K/M结尾
        if text.endswith("K"):
            return eval(text[:-1]) * 1000
        if text.endswith("M"):
            return eval(text[:-1]) * 1000000
        # 普通数字
        return eval(text)

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

    def _readtext(self, img, allowlist: List[str] = None, paragraph=True):
        result = self.reader.readtext(
            img,
            allowlist=allowlist,
            paragraph=paragraph,
        )
        return result[0][1]
