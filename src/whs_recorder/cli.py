import argparse

import cv2

from .evidence_builder import build_evidence
from .redaction import load_redaction_config
from .utils import ensure_parent_dir


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="whs-recorder")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mark", help="Record step markers (smart + manual labels)")
    m.add_argument("--out", required=True, help="Output step_markers.json path")
    m.add_argument("--monitor", type=int, default=1, help="Monitor index (1=primary)")
    m.add_argument("--threshold", type=float, default=7.5, help="Screen change threshold (higher=fewer steps)")
    m.add_argument("--min-gap", type=float, default=0.75, help="Min seconds between steps")
    m.add_argument("--post-delay", type=float, default=0.30, help="Delay after click/enter before diff check")

    b = sub.add_parser("build", help="Build Word evidence from video + markers")
    b.add_argument("--video", required=True, help="MP4 input path")
    b.add_argument("--markers", required=True, help="step_markers.json path")
    b.add_argument("--out", required=True, help="Output folder")
    b.add_argument("--title", default="WHS Mobile – Test Evidence", help="Document title")
    b.add_argument("--skip-loading", action="store_true", help="Skip markers flagged as loading")
    b.add_argument("--redact", help="Redaction rules JSON applied to every screenshot")
    b.add_argument("--result-window", type=float, default=2.5,
                   help="Seconds after a marker to search for the result message")
    b.add_argument("--no-toast", action="store_true",
                   help="Disable result-message detection and use --result-offsets instead")
    b.add_argument("--result-offsets", default="0.6,1.2",
                   help="Seconds after marker to look for result message (used when no message is detected)")

    r = sub.add_parser("redact-preview", help="Apply redaction rules to one image, to tune the rules")
    r.add_argument("--image", required=True, help="Screenshot to redact")
    r.add_argument("--redact", required=True, help="Redaction rules JSON")
    r.add_argument("--out", required=True, help="Output image path")
    r.add_argument("--label", action="store_true", help="Outline and name each redacted area")

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.cmd == "mark":
        # Imported here so `build` works on machines without the capture stack
        # (pynput, mss and tkinter are only needed while recording).
        from .marker_recorder import run_marker_recorder

        run_marker_recorder(
            out_path=args.out,
            monitor_index=args.monitor,
            diff_threshold=args.threshold,
            min_gap_sec=args.min_gap,
            post_delay_sec=args.post_delay,
        )
        return

    if args.cmd == "build":
        offsets = [float(x.strip()) for x in args.result_offsets.split(",") if x.strip()]
        build_evidence(
            video=args.video,
            markers=args.markers,
            out_dir=args.out,
            title=args.title,
            skip_loading=args.skip_loading,
            result_offsets=offsets,
            redaction=load_redaction_config(args.redact),
            result_window=args.result_window,
            detect_toast=not args.no_toast,
        )
        return

    if args.cmd == "redact-preview":
        config = load_redaction_config(args.redact)
        if config.label is False and args.label:
            config.label = True
        image = cv2.imread(args.image)
        if image is None:
            raise SystemExit(f"Cannot read image: {args.image}")
        ensure_parent_dir(args.out)
        cv2.imwrite(args.out, config.apply(image))
        print(f"Applied {config.describe()} -> {args.out}")
        return


if __name__ == "__main__":
    main()
