# -*- coding: utf-8 -*-
"""
外部 OCR 引擎封装模块
支持：百度智能云、阿里云、腾讯云
"""

import base64
import json
import os
import sys
import time
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import requests


class BaseOCREngine(ABC):
    """OCR 引擎抽象基类"""

    @abstractmethod
    def recognize_image(self, image_path: str) -> str:
        """识别单张图片，返回纯文本"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass


class BaiduOCR(BaseOCREngine):
    """
    百度智能云通用文字识别（高精度版）
    文档：https://ai.baidu.com/ai-doc/OCR/zk3h7xz52
    免费额度：个人用户每月 5 万次（高精度版 1 万次/月）
    """

    def __init__(self, app_id: str, api_key: str, secret_key: str):
        self.app_id = app_id
        self.api_key = api_key
        self.secret_key = secret_key
        self._access_token: Optional[str] = None

    @property
    def name(self) -> str:
        return "baidu"

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        url = (
            "https://aip.baidubce.com/oauth/2.0/token"
            f"?grant_type=client_credentials&client_id={self.api_key}&client_secret={self.secret_key}"
        )
        resp = requests.post(url, timeout=30)
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"百度 OCR token 获取失败: {data}")
        self._access_token = data["access_token"]
        return self._access_token

    def recognize_image(self, image_path: str) -> str:
        token = self._get_access_token()
        # 高精度版接口
        url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic?access_token={token}"

        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        payload = {
            "image": img_b64,
            "language_type": "CHN_ENG",
            "detect_direction": "true",
            "paragraph": "true",   # 输出段落信息，方便排版
        }
        resp = requests.post(url, data=payload, headers=headers, timeout=60)
        data = resp.json()

        if "error_code" in data:
            raise RuntimeError(f"百度 OCR 错误 {data['error_code']}: {data.get('error_msg')}")

        words = []
        for item in data.get("words_result", []):
            words.append(item.get("words", ""))
        return "\n".join(words)


class AliyunOCR(BaseOCREngine):
    """
    阿里云视觉智能 - 通用文字识别（RecognizeAdvanced）
    文档：https://help.aliyun.com/document_detail/155645.html
    免费额度：每月 1 万次左右（以官网为准）
    需要先 pip install alibabacloud_ocr_api20210707
    """

    def __init__(self, access_key_id: str, access_key_secret: str):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self._client = None

    @property
    def name(self) -> str:
        return "aliyun"

    def _get_client(self):
        if self._client is None:
            try:
                from alibabacloud_ocr_api20210707.client import Client as OcrClient
                from alibabacloud_tea_openapi import models as open_api_models
            except ImportError as e:
                raise ImportError("使用阿里云 OCR 需要先安装 SDK: pip install alibabacloud_ocr_api20210707") from e

            config = open_api_models.Config(
                access_key_id=self.access_key_id,
                access_key_secret=self.access_key_secret,
            )
            config.endpoint = "ocr-api.cn-hangzhou.aliyuncs.com"
            self._client = OcrClient(config)
        return self._client

    def recognize_image(self, image_path: str) -> str:
        from alibabacloud_ocr_api20210707 import models as ocr_models

        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        client = self._get_client()
        request = ocr_models.RecognizeAdvancedRequest(body=ocr_models.RecognizeAdvancedRequestBody(url=None, body=img_b64))
        resp = client.recognize_advanced(request)
        body = resp.body
        if body.code != "200" and body.code != "OK":
            raise RuntimeError(f"阿里云 OCR 错误: {body.code} {body.message}")

        data = json.loads(body.data) if isinstance(body.data, str) else body.data
        words = []
        for item in data.get("prism_wordsInfo", []):
            words.append(item.get("word", ""))
        return "\n".join(words)


class TencentOCR(BaseOCREngine):
    """
    腾讯云通用印刷体识别（高精度版）
    文档：https://cloud.tencent.com/document/product/866/33526
    免费额度：每月 1 万次（以官网为准）
    需要先 pip install tencentcloud-sdk-python-ocr
    """

    def __init__(self, secret_id: str, secret_key: str, region: str = "ap-guangzhou"):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.region = region
        self._client = None

    @property
    def name(self) -> str:
        return "tencent"

    def _get_client(self):
        if self._client is None:
            try:
                from tencentcloud.common.credential import Credential
                from tencentcloud.common.profile.client_profile import ClientProfile
                from tencentcloud.common.profile.http_profile import HttpProfile
                from tencentcloud.ocr.v20181119 import ocr_client
            except ImportError as e:
                raise ImportError("使用腾讯云 OCR 需要先安装 SDK: pip install tencentcloud-sdk-python-ocr") from e

            cred = Credential(self.secret_id, self.secret_key)
            http_profile = HttpProfile(reqMethod="POST", reqTimeout=60)
            client_profile = ClientProfile(httpProfile=http_profile)
            self._client = ocr_client.OcrClient(cred, self.region, client_profile)
        return self._client

    def recognize_image(self, image_path: str) -> str:
        from tencentcloud.ocr.v20181119 import models

        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        req = models.GeneralAccurateOCRRequest()
        req.ImageBase64 = img_b64
        client = self._get_client()
        resp = client.GeneralAccurateOCR(req)

        words = []
        for item in resp.TextDetections:
            words.append(item.DetectedText)
        return "\n".join(words)


def build_ocr_engine() -> BaseOCREngine:
    """
    根据环境变量自动创建 OCR 引擎实例，优先级：百度 > 阿里 > 腾讯
    """
    # 百度
    baidu_app_id = os.getenv("BAIDU_OCR_APP_ID")
    baidu_api_key = os.getenv("BAIDU_OCR_API_KEY")
    baidu_secret_key = os.getenv("BAIDU_OCR_SECRET_KEY")
    if baidu_api_key and baidu_secret_key:
        return BaiduOCR(baidu_app_id or "", baidu_api_key, baidu_secret_key)

    # 阿里
    ali_key_id = os.getenv("ALIYUN_OCR_ACCESS_KEY_ID")
    ali_key_secret = os.getenv("ALIYUN_OCR_ACCESS_KEY_SECRET")
    if ali_key_id and ali_key_secret:
        return AliyunOCR(ali_key_id, ali_key_secret)

    # 腾讯
    tx_secret_id = os.getenv("TENCENT_OCR_SECRET_ID")
    tx_secret_key = os.getenv("TENCENT_OCR_SECRET_KEY")
    if tx_secret_id and tx_secret_key:
        return TencentOCR(tx_secret_id, tx_secret_key)

    raise RuntimeError(
        "未找到任何 OCR 服务配置。请至少配置一组环境变量：\n"
        "  百度: BAIDU_OCR_APP_ID, BAIDU_OCR_API_KEY, BAIDU_OCR_SECRET_KEY\n"
        "  阿里: ALIYUN_OCR_ACCESS_KEY_ID, ALIYUN_OCR_ACCESS_KEY_SECRET\n"
        "  腾讯: TENCENT_OCR_SECRET_ID, TENCENT_OCR_SECRET_KEY"
    )
