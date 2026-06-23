from __future__ import annotations

from pathlib import Path

import cv2


BASE_DIR = Path(__file__).resolve().parent
VIDEO_PATH = BASE_DIR / "P15_t3_recording.mp4"
OUTPUT_DIR = BASE_DIR / "paper_frames"

AOI_COLORS_HEX = {
	"Patch": "#d7301f",
	"Browser": "#3182bd",
	"Test and Runtime Feedback": "#31a354",
	"Tests": "#fd8d3c",
	"Source Code": "#756bb1",
	"Other": "#bdbdbd",
}

# Label aliases so figure text can stay natural while colors remain consistent.
LABEL_TO_AOI = {
	"Patch": "Patch",
	"Browser": "Browser",
	"Tests": "Tests",
	"Test and Runtime Feedback": "Test and Runtime Feedback",
}


def mmss_to_seconds(value: str) -> int:
	parts = [int(part) for part in value.split(":")]
	if len(parts) == 2:
		return parts[0] * 60 + parts[1]
	if len(parts) == 3:
		return parts[0] * 3600 + parts[1] * 60 + parts[2]
	raise ValueError(f"Unsupported timestamp format: {value}")


FRAME_SPECS = [
	{
		"name": "patch",
		"timestamp": "0:17",
		"label": "Patch",
		"boxes": [
			# Starter box; adjust after review.
			(0.62, 0.20, 0.33, 0.22, "Patch"),
		],
	},
	{
		"name": "browser",
		"timestamp": "17:33",
		"label": "Browser",
		"boxes": [
			# Browser takes most of the frame except a bottom bar.
			(0.01, 0.01, 0.98, 0.88, "Browser"),
		],
	},
	{
		"name": "tests_output",
		"timestamp": "6:56",
		"label": "Tests + Test and Runtime Feedback",
		"boxes": [
			# Starter boxes; adjust after review.
			(0.02, 0.57, 0.45, 0.40, "Tests"),
			(0.49, 0.57, 0.49, 0.40, "Test and Runtime Feedback"),
		],
	},
]


def hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
	hex_clean = hex_color.lstrip("#")
	r = int(hex_clean[0:2], 16)
	g = int(hex_clean[2:4], 16)
	b = int(hex_clean[4:6], 16)
	return (b, g, r)


def draw_labeled_box(
	image,
	box_norm: tuple[float, float, float, float, str],
) -> None:
	x_norm, y_norm, w_norm, h_norm, text = box_norm
	h, w = image.shape[:2]
	aoi_name = LABEL_TO_AOI.get(text, "Other")
	color = hex_to_bgr(AOI_COLORS_HEX.get(aoi_name, AOI_COLORS_HEX["Other"]))

	x1 = int(x_norm * w)
	y1 = int(y_norm * h)
	x2 = int((x_norm + w_norm) * w)
	y2 = int((y_norm + h_norm) * h)

	cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)

	font = cv2.FONT_HERSHEY_SIMPLEX
	scale = 0.8
	thickness = 2
	text_size, _ = cv2.getTextSize(text, font, scale, thickness)
	text_w, text_h = text_size

	label_top = max(0, y1 - text_h - 10)
	label_bottom = y1
	label_right = min(w, x1 + text_w + 10)

	cv2.rectangle(image, (x1, label_top), (label_right, label_bottom), color, -1)
	cv2.putText(image, text, (x1 + 5, label_bottom - 5), font, scale, (0, 0, 0), thickness, cv2.LINE_AA)


def extract_frame(video_capture: cv2.VideoCapture, timestamp_seconds: int):
	video_capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_seconds * 1000)
	ok, frame = video_capture.read()
	if not ok:
		raise RuntimeError(f"Could not read frame at {timestamp_seconds} seconds.")
	return frame


def main() -> None:
	if not VIDEO_PATH.exists():
		raise FileNotFoundError(f"Video not found: {VIDEO_PATH}")

	OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

	cap = cv2.VideoCapture(str(VIDEO_PATH))
	if not cap.isOpened():
		raise RuntimeError(f"Failed to open video: {VIDEO_PATH}")

	try:
		for spec in FRAME_SPECS:
			timestamp_seconds = mmss_to_seconds(spec["timestamp"])
			frame = extract_frame(cap, timestamp_seconds)

			for box in spec["boxes"]:
				draw_labeled_box(frame, box)

			out_name = f"P15_t3_{spec['name']}_{spec['timestamp'].replace(':', '-')}.png"
			out_path = OUTPUT_DIR / out_name
			ok = cv2.imwrite(str(out_path), frame)
			if not ok:
				raise RuntimeError(f"Failed to save image: {out_path}")
			print(f"Wrote {out_path.name}")
	finally:
		cap.release()


if __name__ == "__main__":
	main()
