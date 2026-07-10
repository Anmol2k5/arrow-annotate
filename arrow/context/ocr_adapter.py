from typing import Any, Dict, List

from PIL import Image


class OCRAdapter:
    """
    Adapts offline OCR engine (RapidOCR/ONNX) to extract text regions
    from screenshot images.
    """
    def __init__(self) -> None:
        pass

    def run_ocr(self, pil_image: Image.Image) -> List[Dict[str, Any]]:
        """
        Runs OCR on a PIL Image. Returns a list of dictionaries with detected
        text, bounding boxes, and confidence.
        """
        from arrow.context.hybrid_pointer import _get_ocr
        ocr = _get_ocr()
        if ocr is None:
            return []
        
        import numpy as np
        img_arr = np.array(pil_image)
        result, _ = ocr(img_arr)
        
        detections = []
        if result:
            for det in result:
                try:
                    box, text, conf = det
                    xs = [int(p[0]) for p in box]
                    ys = [int(p[1]) for p in box]
                    detections.append({
                        "text": text,
                        "confidence": float(conf),
                        "bounding_box": (min(xs), min(ys), max(xs), max(ys))
                    })
                except Exception:
                    continue
        return detections
