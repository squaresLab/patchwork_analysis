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
			(0.24, 0.061, 0.735, 0.563, "Patch"),
		],
	},
	{
		"name": "browser",
		"timestamp": "17:33",
		"label": "Browser",
		"boxes": [
			# Browser takes most of the frame except a bottom bar.
			(0.0012, 0.0012, (1.00 - .0024), 0.96, "Browser"),
		],
	},
	{
		"name": "tests_output",
		"timestamp": "6:56",
		"label": "Tests + Test and Runtime Feedback",
		"boxes": [
			# Starter boxes; adjust after review.
			(0.24, 0.061, 0.735, 0.563, "Tests"),
			(0.02, 0.628, 0.954, 0.3, "Test and Runtime Feedback", "top_right"),
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
	box_norm: tuple[float, float, float, float, str] | tuple[float, float, float, float, str, str],
) -> None:
	if len(box_norm) == 6:
		x_norm, y_norm, w_norm, h_norm, text, label_anchor = box_norm
	else:
		x_norm, y_norm, w_norm, h_norm, text = box_norm
		label_anchor = "top_left"

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
	box_w = max(1, x2 - x1)
	box_h = max(1, y2 - y1)
	inset = 6
	label_pad = 6

	# Keep labels inside the box and reduce font size when needed.
	while scale > 0.4:
		text_size, _ = cv2.getTextSize(text, font, scale, thickness)
		text_w, text_h = text_size
		fits_width = text_w + 2 * label_pad <= box_w - 2 * inset
		fits_height = text_h + 2 * label_pad <= box_h - 2 * inset
		if fits_width and fits_height:
			break
		scale -= 0.1

	text_size, _ = cv2.getTextSize(text, font, scale, thickness)
	text_w, text_h = text_size
	label_w = text_w + 2 * label_pad
	label_h = text_h + 2 * label_pad

	if label_anchor == "top_right":
		label_x2 = x2 - inset
		label_x1 = max(x1 + inset, label_x2 - label_w)
	else:
		label_x1 = x1 + inset
		label_x2 = min(x2 - inset, label_x1 + label_w)

	label_y1 = y1 + inset
	label_y2 = min(y2 - inset, label_y1 + label_h)

	cv2.rectangle(image, (label_x1, label_y1), (label_x2, label_y2), color, -1)
	text_x = label_x1 + label_pad
	text_y = label_y1 + label_pad + text_h
	cv2.putText(image, text, (text_x, text_y), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)


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
