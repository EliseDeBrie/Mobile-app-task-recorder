# Security

What the program does that a security desk will want to know about, what has
been done about it, and how to report a problem. Nothing here cost money: the
measures are the free ones, chosen because the tool is given away.

## Reporting a vulnerability

Open a private report through the repository's **Security** tab ("Report a
vulnerability"), or an ordinary issue if the problem is not sensitive. Expect an
answer within a couple of weeks; the tool is maintained by one person in their
own time. Fixes ship as a new release on the Releases page.

## What the program is, in security terms

WHS Task Recorder is a desktop program for Windows that, while a recording
runs, captures one region of the screen and listens to mouse clicks and a few
keys through the ordinary Windows input hooks. That is exactly what a screen
recorder or a hotkey tool does, and it is the reason a security scanner may
flag it: a global input hook is also what a keylogger uses.

The difference is in what is kept, and the source is open so it can be checked:

* The keyboard hook keeps a set of which modifier keys are currently held and
  reacts to Enter. No key text is stored, logged or written anywhere
  (`marker_recorder.py`, the `pressed` set).
* The mouse hook keeps the position of the last click, to mark it on the
  screenshot and to know a tap happened.
* Screenshots are of the chosen rectangle only, and only while recording.
* Everything is written into the folder the user chose. Nothing is written to
  the registry, to a hidden folder or to a server.
* There is no network code in the program. No HTTP, no sockets, no DNS. It can
  run on a machine with no connection and behaves the same.
* It asks for no administrator rights and does not elevate.

## What has been done

**The program**

* A recording file (`recording.json`) is shared between people, and the paths
  in it decide which pictures go into the document. Those paths are confined to
  the recording's own folder: a path that climbs out of it, or an absolute path
  elsewhere, is treated as a missing screenshot and never read. Without this a
  crafted recording could have pulled any picture on the machine into a
  document that was then shared on.
* The document is written with python-docx from the program's own template;
  nothing from a recording is executed or interpreted as markup.
* Screenshots are decoded by OpenCV. A recording from an untrusted source
  therefore means untrusted image files being parsed; OpenCV's image decoders
  are kept current through the dependency pins below.

**The supply chain**

* The dependencies the released program is built from are pinned to exact
  versions in `packaging/constraints.txt`, so a release can be rebuilt and it is
  known what went into it.
* Every CI run audits the installed packages against the vulnerability
  databases with `pip-audit` and fails on a finding.
* Dependabot watches those pins and the workflow's actions and opens a pull
  request when a fix is out.
* The GitHub Actions the workflow runs are pinned to commit hashes, not to
  version tags, and the workflow token can only read the repository except in
  the one job that attaches a release.
* The Store package is the folder form of the program: nothing is unpacked into
  a temporary folder at start-up, which is where the single-file `.exe` is
  weaker (a writable temp folder is a place something else on the machine
  could tamper with between start-ups).

## Known limits

* **The `.exe` on the Releases page is not code-signed.** Windows warns about
  it on first run and SmartScreen may need "Run anyway". A certificate costs
  money and the tool is free, so the signed route is the Store: the Store signs
  the package itself, at no cost. See [STORE.md](STORE.md).
* **Recordings are sensitive by construction.** They hold what was on the
  screen. Treat the recording folder as you would the document, and read the
  redaction section of [PRIVACY.md](PRIVACY.md).
* **A Tesseract next to the program is trusted.** When Tesseract is used, the
  program looks for it in a `tesseract` folder beside its own executable, in
  `%LOCALAPPDATA%\whs-recorder\tesseract`, and on the path. Anyone who can
  write there can substitute the binary - but anyone who can write beside the
  program can replace the program too. Windows OCR, the default, has no such
  folder.
* **A warehouse app running as administrator is invisible to the recorder** when
  the recorder runs as a normal user, which is Windows keeping a lower process
  out of a higher one. Run both the same way; do not run the recorder elevated
  to work around it.
