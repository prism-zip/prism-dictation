### Prism Dictation

*** This is a fork of https://github.com/ideasman42/nerd-dictation; the nomenclature change to "prism" is for the prism-archive and related prism-project software, which utilize a standard build and distribution system. ***


*Offline Speech to Text for Desktop Linux.* - See `demo video <https://www.youtube.com/watch?v=T7sR-4DFhpQ>`

This is a utility that provides simple access speech to text for using in Linux
without being tied to a desktop environment, using the excellent `VOSK-API <https://github.com/alphacep/vosk-api>`


Simple
   This is a single file Python script with minimal dependencies.
Hackable
   User configuration lets you manipulate text using Python string operations.
Zero Overhead
   As this relies on manual activation there are no background processes.

Dictation is accessed manually with begin/end commands.


Usage
========

# Don't use bin_dist if you're a purist; these binaries are created with Nuitka.

It is suggested to bind begin/end/cancel to shortcut keys.

``` bash
   prism-dictation.py begin --vosk-model-dir=./model
```

use ctrl + c to stop


if used with "&": prism-dictation.py begin --vosk-model-dir=./model &

``` bash
   prism-dictation end
```

For details on how this can be used, see:
``prism-dictation --help`` and ``prism-dictation begin --help``.


Features
========

Specific features include:

Numbers as Digits
   Optional conversion from numbers to digits.

   So ``Three million five hundred and sixty second`` becomes ``3,000,562nd``.

   A series of numbers (such as reciting a phone number) is also supported.

   So ``Two four six eight`` becomes ``2,468``.

1. **Time Out**

   Optionally end speech to text early when no speech is detected for a given number of seconds.
   (without an explicit call to ``end`` which is otherwise required).

2. **Output Type**

   Output can simulate keystroke events (default) or simply print to the standard output.

3. **User Configuration Script**

   User configuration is just a Python script which can be used to manipulate text using Python's full feature set.

Suspend/Resume
   Initial load time can be an issue for users on slower systems or with some of the larger language-models,
   in this case suspend/resume can be useful.
   While suspended all data is kept in memory and the process is stopped.
   Audio recording is stopped and restarted on resume.

See ``prism-dictation begin --help`` for details on how to access these options.


Dependencies
============

- Python 3.6 (or newer).
- The VOSK-API.
- An audio recording utility (``parec`` by default).
- An input simulation utility (``xdotool`` by default).


Audio Recording Utilities
-------------------------

You may select one of the following tools.

- ``parec`` command for recording from pulse-audio.
- ``sox`` command as alternative, see the guide: `Using sox with prism-dictation <readme-sox.rst>`_.


Input Simulation Utilities
--------------------------

You may select one of the following input simulation utilities.

- `xdotool <https://github.com/jordansissel/xdotool>`__ command to simulate input in X11.
- `ydotool <https://github.com/ReimuNotMoe/ydotool>`__ command to simulate input anywhere (X11/Wayland/TTYs).
  See the setup guide: `Using ydotool with prism-dictation <readme-ydotool.rst>`_.
- `dotool <https://git.sr.ht/~geb/dotool>`__ command to simulate input anywhere (X11/Wayland/TTYs).
- `wtype <https://github.com/atx/wtype>`__ to simulate input in Wayland".


Install
=======

use scripts/install.sh

```bash

   git clone https://github.com/prism-zip/prism-dictation.git
   cd prism-dictation
   sh scripts/install.sh

```

- Reminder that it's up to you to bind begin/end/cancel to actions you can easily access (typically key shortcuts).
- To avoid having to pass the ``--vosk-model-dir`` argument, copy the model to the default path:

```bash

   mkdir -p ~/.config/prism-dictation
   mv ./model ~/.config/prism-dictation

```

.. hint::

   Once this is working properly you may wish to download one of the larger language models for more accurate dictation.
   They are available `here <https://alphacephei.com/vosk/models>`


If you prefer to use a package, see: `Packaging <package/readme.rst>`_.


Configuration
=============

This is an example of a trivial configuration file which simply makes the input text uppercase.

.. code-block:: python

   # ~/.config/prism-dictation/prism-dictation.py
   def nerd_dictation_process(text):
       return text.upper()


A more comprehensive configuration is included in the ``examples/`` directory.

Hints
-----

- The processing function can be used to implement your own actions using keywords of your choice.
  Simply return a blank string if you have implemented your own text handling.

- Context sensitive actions can be implemented using command line utilities to access the active window.


Paths
=====

Local Configuration
   ``~/.config/prism-dictation/prism-dictation.py``
Language Model
   ``~/.config/prism-dictation/model``

   Note that ``--vosk-model-dir=PATH`` can be used to override the default.


