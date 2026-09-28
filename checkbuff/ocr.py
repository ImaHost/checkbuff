"""Windows 내장 OCR(Windows.Media.Ocr) 래퍼. 반드시 사용하는 스레드 안에서 생성할 것."""
import asyncio
import io
from dataclasses import dataclass

from PIL import Image


class OcrUnavailable(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float

    @property
    def x1(self):
        return self.x + self.w

    @property
    def y1(self):
        return self.y + self.h

    @property
    def cy(self):
        return self.y + self.h / 2


class WindowsOcr:
    def __init__(self, lang: str = "ko"):
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.graphics.imaging import BitmapDecoder
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
        except ImportError as e:
            raise OcrUnavailable(f"winrt 패키지가 없습니다: {e}") from e
        self._BitmapDecoder = BitmapDecoder
        self._DataWriter = DataWriter
        self._Stream = InMemoryRandomAccessStream
        self.engine = OcrEngine.try_create_from_language(Language(lang))
        if self.engine is None:
            raise OcrUnavailable(
                "Windows 한국어 OCR을 사용할 수 없습니다.\n"
                "설정 > 시간 및 언어 > 언어 및 지역 > 한국어 > 언어 옵션에서 "
                "'광학 문자 인식'을 설치하세요."
            )
        self.max_dim = int(OcrEngine.max_image_dimension)
        self.loop = asyncio.new_event_loop()

    def recognize(self, img: Image.Image, scale: float = 1.0) -> list[Word]:
        """img 를 인식하고 단어 좌표를 scale 로 나눠 원본 좌표로 돌려준다."""
        return self.loop.run_until_complete(self._recognize(img, scale))

    async def _recognize(self, img, scale):
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        stream = self._Stream()
        writer = self._DataWriter(stream)
        writer.write_bytes(buf.getvalue())
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await self._BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await self.engine.recognize_async(bitmap)
        words = []
        for line in result.lines:
            for w in line.words:
                r = w.bounding_rect
                words.append(Word(w.text, r.x / scale, r.y / scale, r.width / scale, r.height / scale))
        return words

    def close(self):
        self.loop.close()
