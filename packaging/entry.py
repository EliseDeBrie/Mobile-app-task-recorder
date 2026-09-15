"""What the packaged program starts at.

With arguments it behaves as the command line; with none, which is what a
double-click gives, the launcher window opens.
"""

import multiprocessing

from whs_recorder.cli import main

if __name__ == "__main__":
    # The launcher starts the program again as a child process; without this,
    # a frozen build can start the whole program over instead.
    multiprocessing.freeze_support()
    main()
