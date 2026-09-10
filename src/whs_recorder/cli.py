import argparse

import cv2

from .evidence_builder import EVIDENCE, STYLES, TASK_GUIDE, build_evidence
from .instructions import EXAMPLE, PREFERRED, VALUE_MODES
from .recording import SUBTASK_START, Recording
from .redaction import load_redaction_config
from .region import resolve_region
from .utils import ensure_parent_dir


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="whs-recorder")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mark", help="Record a task recording (steps, subtasks, info steps)")
    m.add_argument("--out", required=True, help="Output recording JSON path")
    m.add_argument("--name", default="", help="Recording name, used as the document title")
    m.add_argument("--description", default="", help="Introduction shown under the title")
    m.add_argument("--region", default="select",
                   help="Part of the screen the app fills: select (drag it out), full, "
                        "window:<title>, or x,y,width,height")
    m.add_argument("--monitor", type=int, default=1,
                   help="Monitor index used when --region is full (1=primary)")
    m.add_argument("--no-screenshots", action="store_true",
                   help="Do not capture screenshots while recording; build from a video instead")
    m.add_argument("--redact", help="Redaction rules JSON applied to screenshots as they are captured")
    m.add_argument("--result-window", type=float, default=2.5,
                   help="Seconds to keep watching after a step for the result message")
    m.add_argument("--threshold", type=float, default=7.5, help="Screen change threshold (higher=fewer steps)")
    m.add_argument("--min-gap", type=float, default=0.75, help="Min seconds between steps")
    m.add_argument("--post-delay", type=float, default=0.30, help="Delay after click/enter before diff check")

    b = sub.add_parser("build", help="Build a Word document from video + recording")
    b.add_argument("--video", default="",
                   help="MP4 screen recording, needed only when the recording holds no screenshots")
    b.add_argument("--markers", required=True, help="Recording JSON path")
    b.add_argument("--out", required=True, help="Output folder")
    b.add_argument("--title", default=None, help="Document title (defaults to the recording name)")
    b.add_argument("--style", choices=STYLES, default=TASK_GUIDE,
                   help="task-guide reproduces the D365 Task Recorder document; evidence pairs action and result")
    b.add_argument("--values", choices=VALUE_MODES, default=PREFERRED,
                   help="preferred repeats the recorded values, example tells the reader to enter their own")
    b.add_argument("--with-result", action="store_true",
                   help="Also place the result screenshot under each step of a task guide")
    b.add_argument("--skip-loading", action="store_true", help="Skip steps flagged as loading")
    b.add_argument("--redact", help="Redaction rules JSON applied to every screenshot")
    b.add_argument("--result-window", type=float, default=2.5,
                   help="Seconds after a step to search for the result message")
    b.add_argument("--no-toast", action="store_true",
                   help="Disable result-message detection and use --result-offsets instead")
    b.add_argument("--result-offsets", default="0.6,1.2",
                   help="Seconds after a step to look for the result message (used when no message is detected)")

    v = sub.add_parser("preview", help="Print the guide text for a recording, without building a document")
    v.add_argument("--markers", required=True, help="Recording JSON path")
    v.add_argument("--values", choices=VALUE_MODES, default=PREFERRED,
                   help="preferred repeats the recorded values, example tells the reader to enter their own")
    v.add_argument("--skip-loading", action="store_true", help="Skip steps flagged as loading")

    g = sub.add_parser("region", help="Drag out a screen region and print it, for scripting")
    g.add_argument("--window", default="", help="Find the region by window title instead of dragging")

    r = sub.add_parser("redact-preview", help="Apply redaction rules to one image, to tune the rules")
    r.add_argument("--image", required=True, help="Screenshot to redact")
    r.add_argument("--redact", required=True, help="Redaction rules JSON")
    r.add_argument("--out", required=True, help="Output image path")
    r.add_argument("--label", action="store_true", help="Outline and name each redacted area")

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.cmd == "mark":
        # Imported here so the other commands work on machines without the
        # capture stack (pynput, mss and tkinter are only needed while recording).
        from .marker_recorder import run_marker_recorder

        # "select" is resolved inside the recorder, which owns the one thread
        # every Tk window has to be created on.
        spec = (args.region or "").strip()
        region = None if spec.lower() == "select" else resolve_region(spec)

        run_marker_recorder(
            out_path=args.out,
            monitor_index=args.monitor,
            diff_threshold=args.threshold,
            min_gap_sec=args.min_gap,
            post_delay_sec=args.post_delay,
            name=args.name,
            description=args.description,
            region=region,
            region_spec=spec,
            capture_screenshots=not args.no_screenshots,
            result_window=args.result_window,
            redaction=load_redaction_config(args.redact),
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
            style=args.style,
            value_mode=args.values,
            include_result=args.with_result,
        )
        return

    if args.cmd == "region":
        region = resolve_region(f"window:{args.window}" if args.window else "select")
        if region is None:
            raise SystemExit("No region selected.")
        print(f"{region.left},{region.top},{region.width},{region.height}")
        return

    if args.cmd == "preview":
        recording = Recording.load(args.markers)
        print(recording.name)
        if recording.description:
            print(recording.description)
        for entry in recording.outline(skip_loading=args.skip_loading):
            indent = "    " * entry.depth
            if entry.kind == SUBTASK_START:
                print(f"\n{indent}[{entry.node.name}]")
                continue
            if entry.node.title:
                print(f"{indent}    {entry.node.title}")
            print(f"{indent}{entry.number:>3}. {entry.node.instruction(args.values)}")
            if entry.node.note:
                print(f"{indent}     ({entry.node.note})")
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
