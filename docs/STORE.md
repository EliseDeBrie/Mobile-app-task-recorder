# Publishing to the Store

What it takes to put the tool on the Microsoft Store without spending anything,
and the order to do it in. The pieces that can be automated are done: CI builds
a Store package on every push. What remains is the account and the listing,
which only the publisher can do.

## Why the Store, and why MSIX

Two routes exist for a desktop program. One takes the `.exe` installer at a URL
you host and requires it to be signed with a certificate from a commercial
authority, which costs a few hundred a year. The other takes an MSIX package
and **the Store signs it for you**: no certificate to buy, no key to keep, and
updates are delivered by the Store. That is the free route, and the one built
here. It also ends the "Windows protected your PC" warning that the unsigned
`.exe` gets, because what the Store installs carries a trusted signature.

## What CI produces

Every run of the Windows workflow builds, next to the `.exe`:

    WHS Task Recorder.msix

made by `packaging/make_msix.py` from a folder build of the program and the
manifest in `packaging/msix/AppxManifest.xml`. It is attached to each release
alongside the `.exe`.

Until the identity below is set, the package carries placeholder values. It is
enough to try out locally; the Store will reject it, by design.

## The steps

1. **Open a developer account.** Start at
   [storedeveloper.microsoft.com](https://storedeveloper.microsoft.com) and
   choose *Individual developer*: through that entry point registration is
   free (the older route through Partner Center directly still shows the
   fee). It needs a personal Microsoft account, not a work one, and identity
   verification with a government ID and a selfie, done from a phone. An
   individual account is the right one for a tool given away outside of
   one's trade; a company account is not needed.

2. **Reserve the app name.** Apps and games > New product > MSIX or PWA app.
   The name must be unique across the Store and free of trademarks. Two things
   to weigh: "Task Recorder" is the name of a feature in someone else's
   product, and the tool is not affiliated with that vendor, so a name that
   does not suggest it is safer, for example *WHS Guide Recorder* or
   *Handheld Task Guide*. A reservation holds for three months.

3. **Copy the identity.** Product management > Product identity shows three
   values. Put them in the repository as *variables* (Settings > Secrets and
   variables > Actions > Variables; they are not secret, but they are not
   source either):

   | Partner Center | Repository variable |
   | --- | --- |
   | Package/Identity/Name | `MSIX_IDENTITY_NAME` |
   | Package/Identity/Publisher | `MSIX_PUBLISHER` |
   | Publisher display name | `MSIX_PUBLISHER_DISPLAY_NAME` |

   The Store checks that the name in the package is one you reserved. The
   reserved name is **Warehouse Step Recorder**, and that is what the two
   `DisplayName` values in `packaging/msix/AppxManifest.xml` say; the
   program's own file name inside the package stays `WHS Task Recorder.exe`.

4. **Build.** Push, or run the workflow by hand. Download
   `WHS Task Recorder.msix` from the run's artifacts, or from the release.

5. **Try it before uploading**, on a Windows 11 machine, from an administrator
   PowerShell (an unsigned package with a program in it installs for all
   users, so it needs one):

       Add-AppxPackage -Path ".\WHS Task Recorder.msix" -AllowUnsigned

   It appears in Start as any installed app. Remove it again with
   `Get-AppxPackage *WHSTaskRecorder* | Remove-AppxPackage`.

6. **Create the submission.** Upload the `.msix` on the Packages page. Partner
   Center validates it on upload and says what is wrong if anything is. Then
   fill in:

   * **Properties** - category *Developer tools* or *Productivity*; the
     privacy policy URL is required for a desktop app, and this one is it:
     `https://github.com/EliseDeBrie/Mobile-app-task-recorder/blob/main/docs/PRIVACY.md`
     (a page on GitHub is a valid URL; it costs nothing to host).
   * **Age ratings** - the questionnaire; the tool has none of the things it
     asks about.
   * **Pricing** - free, all markets.
   * **Store listing** - a draft is below. Screenshots of the launcher, the
     recorder bar beside the app, the review window and a page of the
     resulting document are what a reader wants to see; at least one is
     required.
   * **Submission options** - in the notes for certification, say what the
     input hooks are for: "While a recording runs, the program listens for
     mouse clicks and the Enter key so that it knows when a step was taken.
     No key text is recorded. See the privacy policy." That is the one thing
     the certification desk may otherwise ask about.

7. **Submit.** Certification is automated and usually takes hours to a few
   days. The Store signs the package and lists it. Later versions are new
   submissions with a higher version number: the `Version` in the package is
   the program's own, with a `.0` on the end, so bumping `pyproject.toml` and
   `whs_recorder/__init__.py` is all that changes.

## Listing text, draft

**Short description.** Records what you do in the Warehouse Management mobile
app and writes it up as a task guide: numbered steps, a screenshot each, in a
Word document. Everything stays on your PC.

**Description.** Finance and operations apps have Task Recorder; the handheld
does not. This tool fills the gap. Drag a box around the warehouse app window,
work through the process, and every tap or Enter that changes the screen is
written down as a step, with the screen as it was when you tapped it. When you
stop, the Word document is made and the steps open in a list for checking:
correct the wording, leave a step out, reorder. The result is the same kind of
task guide, with the same step sentences, that Task Recorder produces for the
web client.

Nothing leaves the machine: no account, no upload, no telemetry. Screen reading
uses the OCR built into Windows. Redaction rules keep names and licence plates
out of the shared document.

WHS Task Recorder is an independent tool and is not affiliated with, or
endorsed by, the vendors of the products it works alongside.

## What was not done, and why

* **Code-signing the `.exe`** on the Releases page. It needs a certificate,
  which costs money. The `.exe` stays as it is, with the "Run anyway" note in
  the README; the Store build is the signed one.
* **A `.msixupload` with symbols** for the Store's crash analytics. It is
  optional; a plain `.msix` is accepted on the Packages page, and a Python
  program has no `.pdb` symbols to add anyway.
