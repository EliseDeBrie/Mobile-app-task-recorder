import argparse
from .marker_recorder import run_marker_recorder
from .evidence_builder import build_evidence

def main():
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
    b.add_argument("--result-offsets", default="0.6,1.2", help="Seconds after marker to look for result message")

    args = p.parse_args()

    if args.cmd == "mark":
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
        )
        return

if __name__ == "__main__":
    main()
