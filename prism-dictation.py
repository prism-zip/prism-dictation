#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later

"""
This is a utility that activates speech to text on Linux.
While it could use any system currently it uses the VOSK-API.
"""

# See: `hacking.rst` for developer notes.

# All built in modules.
import argparse
import os
import stat
import subprocess
import sys
import tempfile
import time

# Types.
from typing import (
    Dict,
    IO,
    List,
    Optional,
    Callable,
    Set,
    Tuple,
)
from types import (
    ModuleType,
)

TEMP_COOKIE_NAME = "prism-dictation.cookie"

USER_CONFIG_DIR = "prism-dictation"

USER_CONFIG = "prism-dictation.py"

SIMULATE_INPUT_CODE_COMMAND = -1


# -----------------------------------------------------------------------------
# General Utilities
#


def run_command_or_exit_on_failure(cmd: List[str]) -> None:
    try:
        subprocess.check_output(cmd)
    # Don't catch other kinds of exceptions as they should never happen
    # and can be considered a severe error which doesn't need to be made "user friendly".
    except FileNotFoundError as ex:
        sys.stderr.write("Command {!r} not found: {!s}\n".format(cmd[0], ex))
        sys.exit(1)


def touch(filepath: str, mtime: Optional[int] = None) -> None:
    if os.path.exists(filepath):
        os.utime(filepath, None if mtime is None else (mtime, mtime))
    else:
        with open(filepath, "ab") as _:
            pass
        if mtime is not None:
            try:
                os.utime(filepath, (mtime, mtime))
            except FileNotFoundError:
                pass


def file_mtime_or_none(filepath: str) -> Optional[int]:
    try:
        # For some reason `mypy` thinks this is a float.
        return int(os.stat(filepath)[stat.ST_MTIME])
    except FileNotFoundError:
        return None


def file_age_in_seconds(filepath: str) -> float:
    """
    Return the age of the file in seconds.
    """
    return time.time() - os.stat(filepath)[stat.ST_MTIME]


def file_remove_if_exists(filepath: str) -> bool:
    try:
        os.remove(filepath)
        return True
    except OSError:
        return False


def file_handle_make_non_blocking(file_handle: IO[bytes]) -> None:
    import fcntl

    # Get current `file_handle` flags.
    flags = fcntl.fcntl(file_handle.fileno(), fcntl.F_GETFL)
    fcntl.fcntl(file_handle, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def execfile(filepath: str, mod: Optional[ModuleType] = None) -> Optional[ModuleType]:
    """
    Execute a file path as a Python script.
    """
    import importlib.util

    if not os.path.exists(filepath):
        raise FileNotFoundError('File not found "{:s}"'.format(filepath))

    mod_name = "__main__"
    mod_spec = importlib.util.spec_from_file_location(mod_name, filepath)
    if mod_spec is None:
        raise Exception("Unable to retrieve the module-spec from %r" % filepath)
    if mod is None:
        mod = importlib.util.module_from_spec(mod_spec)

    # While the module name is not added to `sys.modules`, it's important to temporarily
    # include this so statements such as `sys.modules[cls.__module__].__dict__` behave as expected.
    # See: https://bugs.python.org/issue9499 for details.
    modules = sys.modules
    mod_orig = modules.get(mod_name, None)
    modules[mod_name] = mod

    # No error suppression, just ensure `sys.modules[mod_name]` is properly restored in the case of an error.
    try:
        # `mypy` doesn't know about this function.
        mod_spec.loader.exec_module(mod)  # type: ignore
    finally:
        if mod_orig is None:
            modules.pop(mod_name, None)
        else:
            modules[mod_name] = mod_orig

    return mod


# -----------------------------------------------------------------------------
# Simulate Input: XDOTOOL
#
def simulate_typing_with_xdotool(delete_prev_chars: int, text: str) -> None:
    cmd = "xdotool"

    # No setup/tear-down.
    if delete_prev_chars == SIMULATE_INPUT_CODE_COMMAND:
        return

    if delete_prev_chars:
        run_command_or_exit_on_failure(
            [
                cmd,
                "key",
                "--",
                *(["BackSpace"] * delete_prev_chars),
            ]
        )

    run_command_or_exit_on_failure(
        [
            cmd,
            "type",
            "--clearmodifiers",
            "--",
            text,
        ]
    )


# -----------------------------------------------------------------------------
# Simulate Input: YDOTOOL
#
def simulate_typing_with_ydotool(delete_prev_chars: int, text: str) -> None:
    cmd = "ydotool"

    # No setup/tear-down.
    if delete_prev_chars == SIMULATE_INPUT_CODE_COMMAND:
        return

    if delete_prev_chars:
        # ydotool's key subcommand works with int key IDs and key states. 14 is
        # the linux keycode for the backspace key, and :1 and :0 respectively
        # stand for "pressed" and "released."
        #
        # The key delay is lower than the typing setting because it applies to
        # each key state change (pressed, released).
        run_command_or_exit_on_failure(
            [
                cmd,
                "key",
                "--key-delay",
                "3",
                "--",
                *(["14:1", "14:0"] * delete_prev_chars),
            ]
        )

    # The low delay value makes typing fast, making the output much snappier
    # than the slow default.
    run_command_or_exit_on_failure(
        [
            cmd,
            "type",
            "--next-delay",
            "5",
            "--",
            text,
        ]
    )


# -----------------------------------------------------------------------------
# Simulate Input: DOTOOL
#

# NOTE: typed as a string for Py3.6 compatibility.
simulate_typing_with_dotool_proc: "Optional[subprocess.Popen[str]]" = None


def simulate_typing_with_dotoolc(delete_prev_chars: int, text: str) -> None:
    simulate_typing_with_dotool(delete_prev_chars, text, cmd="dotoolc")


def simulate_typing_with_dotool(delete_prev_chars: int, text: str, cmd: str = "dotool") -> None:
    if delete_prev_chars == SIMULATE_INPUT_CODE_COMMAND:
        global simulate_typing_with_dotool_proc
        if text == "SETUP":
            # If this isn't true, something strange is going on.
            assert simulate_typing_with_dotool_proc is None
            # "text" was added as a more readable alias for
            # "universal_newlines" in Python 3.7 so use universal_newlines for
            # Python 3.6 compatibility:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, universal_newlines=True)
            assert proc.stdin is not None
            proc.stdin.write("keydelay 4\nkeyhold 0\ntypedelay 12\ntypehold 0\n")
            proc.stdin.flush()
            simulate_typing_with_dotool_proc = proc
        elif text == "TEARDOWN":
            import signal

            assert simulate_typing_with_dotool_proc is not None
            os.kill(simulate_typing_with_dotool_proc.pid, signal.SIGINT)
            # Not needed, just basic hygiene not to keep killed process reference.
            simulate_typing_with_dotool_proc = None
        else:
            raise Exception("Internal error, unknown command {!r}".format(text))
        return

    assert simulate_typing_with_dotool_proc is not None
    proc = simulate_typing_with_dotool_proc
    assert proc.stdin is not None
    if delete_prev_chars:
        proc.stdin.write("key" + (" backspace" * delete_prev_chars) + "\n")
        proc.stdin.flush()

    proc.stdin.write("type " + text + "\n")
    proc.stdin.flush()


# -----------------------------------------------------------------------------
# Simulate Input: WTYPE
#
def simulate_typing_with_wtype(delete_prev_chars: int, text: str) -> None:
    cmd = "wtype"

    # No setup/tear-down.
    if delete_prev_chars == SIMULATE_INPUT_CODE_COMMAND:
        return

    if delete_prev_chars:
        run_command_or_exit_on_failure(
            [
                cmd,
                "-s",
                "5",
                *(["-k", "backSpace"] * delete_prev_chars),
            ]
        )

    run_command_or_exit_on_failure(
        [
            cmd,
            text,
        ]
    )


# -----------------------------------------------------------------------------
# Simulate Input: STDOUT
#
def simulate_typing_with_stout(delete_prev_chars: int, text: str) -> None:
    cmd = "stdout"

    # No setup/tear-down.
    if delete_prev_chars == SIMULATE_INPUT_CODE_COMMAND:
        return

    if delete_prev_chars:
        sys.stdout.write("\x08" * delete_prev_chars)

    sys.stdout.write(text)
    sys.stdout.flush()


# -----------------------------------------------------------------------------
# Custom Configuration
#


def calc_user_config_path(rest: Optional[str]) -> str:
    """
    Path to the user's configuration directory.
    """
    base = os.environ.get("XDG_CONFIG_HOME")
    if base is None:
        base = os.path.expanduser("~")
        if os.name == "posix":
            base = os.path.join(base, ".config")

    base = os.path.join(base, USER_CONFIG_DIR)
    if rest:
        base = os.path.join(base, rest)
    return base


def user_config_as_module_or_none(
    config_override: Optional[str],
    user_config_prev: Optional[ModuleType],
) -> Optional[ModuleType]:
    # Explicitly ask for no configuration.
    if config_override == "":
        return None
    if config_override is None:
        user_config_path = calc_user_config_path(USER_CONFIG)
        if not os.path.exists(user_config_path):
            return None
    else:
        user_config_path = config_override
        # Allow the exception for a custom configuration.

    try:
        user_config = execfile(user_config_path)
    except Exception as ex:
        sys.stderr.write('Failed to run "{:s}" with error: {:s}\n'.format(user_config_path, str(ex)))
        if user_config_prev is not None:
            # Reloading configuration at run-time, don't exit in this case - use the previous config instead.
            sys.stderr.write("Reload failed, continuing with previous configuration.\n")
            user_config = user_config_prev
        else:
            # Exit if the user starts with an invalid configuration.
            sys.exit(1)

    return user_config


# -----------------------------------------------------------------------------
# Number Parsing
#
# Note this could be extracted into it's own small library.


def from_words_to_digits_setup_once() -> (
    Tuple[Dict[str, Tuple[int, int, str, bool]], Set[str], Set[str], Set[str], Set[str]]
):
    number_words = {}
    # A set of words that can be used to start numeric expressions.
    valid_digit_words: Set[str] = set()

    # Singles.
    units = (
        (("zero", ""), ("zeroes", "'s"), ("zeroth", "th")),
        (("one", ""), ("ones", "'s"), ("first", "st")),
        (("two", ""), ("twos", "'s"), ("second", "nd")),
        (("three", ""), ("threes", "'s"), ("third", "rd")),
        (("four", ""), ("fours", "'s"), ("fourth", "th")),
        (("five", ""), ("fives", "'s"), ("fifth", "th")),
        (("six", ""), ("sixes", "'s"), ("sixth", "th")),
        (("seven", ""), ("sevens", "'s"), ("seventh", "th")),
        (("eight", ""), ("eights", "'s"), ("eighth", "th")),
        (("nine", ""), ("nines", "'s"), ("ninth", "th")),
        (("ten", ""), ("tens", "'s"), ("tenth", "th")),
        (("eleven", ""), ("elevens", "'s"), ("eleventh", "th")),
        (("twelve", ""), ("twelves", "'s"), ("twelfth", "th")),
        (("thirteen", ""), ("thirteens", "'s"), ("thirteenth", "th")),
        (("fourteen", ""), ("fourteens", "'s"), ("fourteenth", "th")),
        (("fifteen", ""), ("fifteens", "'s"), ("fifteenth", "th")),
        (("sixteen", ""), ("sixteens", "'s"), ("sixteenth", "th")),
        (("seventeen", ""), ("seventeens", "'s"), ("seventeenth", "th")),
        (("eighteen", ""), ("eighteens", "'s"), ("eighteenth", "th")),
        (("nineteen", ""), ("nineteens", "'s"), ("nineteenth", "th")),
    )

    # Tens.
    units_tens = (
        (("", ""), ("", ""), ("", "")),
        (("", ""), ("", ""), ("", "")),
        (("twenty", ""), ("twenties", "'s"), ("twentieth", "th")),
        (("thirty", ""), ("thirties", "'s"), ("thirtieth", "th")),
        (("forty", ""), ("forties", "'s"), ("fortieth", "th")),
        (("fifty", ""), ("fifties", "'s"), ("fiftieth", "th")),
        (("sixty", ""), ("sixties", "'s"), ("sixtieth", "th")),
        (("seventy", ""), ("seventies", "'s"), ("seventieth", "th")),
        (("eighty", ""), ("eighties", "'s"), ("eightieth", "th")),
        (("ninety", ""), ("nineties", "'s"), ("ninetieth", "th")),
    )

    # Larger scales.
    scales = (
        ((("hundred", ""), ("hundreds", "s"), ("hundredth", "th")), 2),
        ((("thousand", ""), ("thousands", "s"), ("thousandth", "th")), 3),
        ((("million", ""), ("millions", "s"), ("millionth", "th")), 6),
        ((("billion", ""), ("billions", "s"), ("billionth", "th")), 9),
        ((("trillion", ""), ("trillions", "s"), ("trillionth", "th")), 12),
        ((("quadrillion", ""), ("quadrillions", "s"), ("quadrillionth", "th")), 15),
        ((("quintillion", ""), ("quintillions", "s"), ("quintillionth", "th")), 18),
        ((("sextillion", ""), ("sextillions", "s"), ("sextillionth", "th")), 21),
        ((("septillion", ""), ("septillions", "s"), ("septillionth", "th")), 24),
        ((("octillion", ""), ("octillions", "s"), ("octillionth", "th")), 27),
        ((("nonillion", ""), ("nonillions", "s"), ("nonillionth", "th")), 30),
        ((("decillion", ""), ("decillions", "s"), ("decillionth", "th")), 33),
        ((("undecillion", ""), ("undecillions", "s"), ("undecillionth", "th")), 36),
        ((("duodecillion", ""), ("duodecillions", "s"), ("duodecillionth", "th")), 39),
        ((("tredecillion", ""), ("tredecillions", "s"), ("tredecillionth", "th")), 42),
        ((("quattuordecillion", ""), ("quattuordecillions", "s"), ("quattuordecillionth", "th")), 45),
        ((("quindecillion", ""), ("quindecillions", "s"), ("quindecillionth", "th")), 48),
        ((("sexdecillion", ""), ("sexdecillions", "s"), ("sexdecillionth", "th")), 51),
        ((("septendecillion", ""), ("septendecillions", "s"), ("septendecillionth", "th")), 54),
        ((("octodecillion", ""), ("octodecillions", "s"), ("octodecillionth", "th")), 57),
        ((("novemdecillion", ""), ("novemdecillions", "s"), ("novemdecillionth", "th")), 60),
        ((("vigintillion", ""), ("vigintillions", "s"), ("vigintillionth", "th")), 63),
        ((("centillion", ""), ("centillions", "s"), ("centillionth", "th")), 303),
    )

    # Divisors (not final).
    number_words["and"] = (1, 0, "", False)

    # Perform our loops and start the swap.
    for idx, word_pairs in enumerate(units):
        for word, suffix in word_pairs:
            number_words[word] = (1, idx, suffix, True)
    for idx, word_pairs in enumerate(units_tens):
        for word, suffix in word_pairs:
            number_words[word] = (1, idx * 10, suffix, True)
    for word_pairs, power in scales:
        for word, suffix in word_pairs:
            number_words[word] = (10**power, 0, suffix, True)

    # Needed for 'imply_single_unit'
    valid_scale_words = set()
    for word_pairs, _power in scales:
        for word, _suffix in word_pairs:
            valid_scale_words.add(word)

    valid_unit_words = set()
    for units_iter in (units, units_tens):
        for word_pairs in units_iter:
            for word, _suffix in word_pairs:
                valid_unit_words.add(word)

    valid_zero_words = {word for (word, _suffix) in units[0]}

    valid_digit_words.update(number_words.keys())
    valid_digit_words.remove("and")
    valid_digit_words.remove("")
    return (
        number_words,
        valid_digit_words,
        valid_unit_words,
        valid_scale_words,
        valid_zero_words,
    )


# Originally based on: https://ao.gl/how-to-convert-numeric-words-into-numbers-using-python/
# A module like class can't be instanced.
class from_words_to_digits:
    (
        _number_words,
        valid_digit_words,
        valid_unit_words,
        valid_scale_words,
        valid_zero_words,
    ) = from_words_to_digits_setup_once()

    @staticmethod
    def _parse_number_as_whole_value(
        word_list: List[str],
        word_list_len: int,
        word_index: int,
        imply_single_unit: bool = False,
        force_single_units: bool = False,
    ) -> Tuple[str, str, int, bool]:
        number_words = from_words_to_digits._number_words
        valid_scale_words = from_words_to_digits.valid_scale_words
        valid_unit_words = from_words_to_digits.valid_unit_words
        valid_zero_words = from_words_to_digits.valid_zero_words

        if imply_single_unit:
            only_scale = True

        # Allow reformatting for a regular number.
        allow_reformat = True

        # Primary loop.
        current = result = 0
        suffix = ""

        # This prevents "one and" from being evaluated.
        is_final = False
        # increment_final = 0  # UNUSED.
        increment_final_real = 0
        scale_final = 0
        word_index_final = -1
        result_final = ("", "", word_index, allow_reformat)

        # Loop while splitting to break into individual words.
        while word_index < word_list_len:
            word_data = number_words.get(word_list[word_index])

            if word_data is None:
                # raise Exception('Illegal word: ' + word)
                break

            # When explicitly stated, the word "zero" should terminate the current number and start a new value.
            # Since it doesn't make sense to say "fifty zero" as it does to say "fifty one".
            if word_index_final != -1 and word_list[word_index] in valid_zero_words:
                break

            # Use the index by the multiplier.
            scale, increment, suffix, is_final = word_data
            increment_real = increment
            if force_single_units:
                if increment != 0:
                    increment = 1

            # This prevents "three and two" from resolving to "5".
            # which we never want, unlike "three hundred and two" which resolves to "302"
            if word_index_final != -1:
                if not is_final:
                    if word_list[word_index_final - 1] in valid_unit_words:
                        break

                # Check the unit words can be combined!
                # Saying "twenty one" makes sense but the following cases don't:
                # - "twenty twelve"
                # - "ninety fifty"
                if scale_final == scale:
                    if word_list[word_index] in valid_unit_words and word_list[word_index_final] in valid_unit_words:
                        if not (increment_final_real >= 20 and increment_real < 10):
                            break

            if imply_single_unit:
                if only_scale:
                    if word_list[word_index] not in valid_scale_words:
                        only_scale = False

                    if only_scale and current == 0 and result == 0:
                        current = 1 * scale
                        word_index += 1
                        break

            current = (current * scale) + increment

            # If larger than 100 then push for a round 2.
            if scale > 100:
                result += current
                current = 0

            word_index += 1

            if is_final:
                result_final = ("{:d}".format(result + current), suffix, word_index, allow_reformat)
                word_index_final = word_index
                scale_final = scale
                # increment_final = increment
                increment_final_real = increment_real

            # Once there is a suffix, don't attempt to parse extra numbers.
            if suffix:
                break

        if not is_final:
            # Use the last final result as the output (this resolves problems with a trailing 'and')
            return result_final

        # Return the result plus the current.
        return "{:d}".format(result + current), suffix, word_index, allow_reformat

    @staticmethod
    def _allow_follow_on_word(w_prev: str, w: str) -> bool:
        valid_unit_words = from_words_to_digits.valid_unit_words
        number_words = from_words_to_digits._number_words

        if not w_prev in valid_unit_words:
            return False
        if not w in valid_unit_words:
            return False
        increment_prev = number_words[w_prev][1]
        increment = number_words[w][1]
        if (increment_prev >= 20) and (increment < 10) and (increment != 0):
            return True
        return False

    @staticmethod
    def parse_number_calc_delimiter_from_series(
        word_list: List[str],
        word_index: int,
        word_index_len: int,
    ) -> int:
        valid_unit_words = from_words_to_digits.valid_unit_words
        number_words = from_words_to_digits._number_words

        i = word_index
        i_span_beg = word_index
        w_prev = ""
        result_prev = None
        result_test = None
        while i < word_index_len:
            w = word_list[i]
            if w not in number_words:
                break

            if (i != word_index) and from_words_to_digits._allow_follow_on_word(word_list[i - 1], w):
                # Don't set `w_prev` so we can detect "thirteen and fifty five" without the last "five" delimiting.
                pass
            else:
                if (w_prev not in {"", "and"}) and w in valid_unit_words:
                    # Exception ... allow "thirty three", two words...
                    result_prev = result_test
                    result_test = from_words_to_digits._parse_number_as_whole_value(
                        word_list,
                        i,  # Limit.
                        i_span_beg,  # Split start.
                        force_single_units=True,
                    )
                    # NOTE: in *almost* all cases this assertion is valid.
                    # `assert i == result_test[2]`.
                    # However these may not be equal if there are multiple disconnected series.
                    # e.g. `twenty twenty and twenty twenty one` -> `2020 and 2021`, see: #92.
                    assert i >= result_test[2]
                    if result_test[2] == i:
                        if result_prev:
                            if len(result_prev[0]) == len(result_test[0]):
                                return result_prev[2]
                    i_span_beg = i
                w_prev = w
            i += 1

        result_prev = result_test
        result_test = from_words_to_digits._parse_number_as_whole_value(
            word_list,
            i,  # Limit.
            i_span_beg,  # Split start.
            force_single_units=True,
        )

        if result_prev:
            if len(result_prev[0]) == len(result_test[0]):
                return result_prev[2]

        return word_index_len

    @staticmethod
    def parse_number_calc_delimiter_from_slide(
        word_list: List[str],
        word_index: int,
        word_index_len: int,
    ) -> int:
        valid_unit_words = from_words_to_digits.valid_unit_words
        number_words = from_words_to_digits._number_words
        i = word_index
        w_prev = ""
        while i < word_index_len:
            w = word_list[i]
            if w not in number_words:
                break
            if (i != word_index) and from_words_to_digits._allow_follow_on_word(word_list[i - 1], w):
                # Don't set `w_prev` so we can detect "thirteen and fifty five" without the last "five" delimiting.
                pass
            else:
                if (w_prev not in {"", "and"}) and w in valid_unit_words:
                    result_test_lhs = from_words_to_digits._parse_number_as_whole_value(
                        word_list,
                        i,  # Limit.
                        word_index,  # Split start.
                        force_single_units=True,
                    )
                    result_test_rhs = from_words_to_digits._parse_number_as_whole_value(
                        word_list,
                        word_index_len,  # Limit.
                        i,  # Split start.
                        force_single_units=True,
                    )

                    # If the number on the right is larger, split here.
                    if len(result_test_lhs[0]) <= len(result_test_rhs[0]):
                        return result_test_lhs[2]

                w_prev = w
            i += 1

        return word_index_len

    @staticmethod
    def parse_number(
        word_list: List[str],
        word_index: int,
        imply_single_unit: bool = False,
    ) -> Tuple[str, str, int, bool]:
        word_list_len = len(word_list)

        # Delimit, prevent accumulating "one hundred two hundred" -> "300" for example.
        word_list_len = from_words_to_digits.parse_number_calc_delimiter_from_series(
            word_list,
            word_index,
            word_list_len,
        )
        word_list_len = from_words_to_digits.parse_number_calc_delimiter_from_slide(
            word_list,
            word_index,
            word_list_len,
        )

        return from_words_to_digits._parse_number_as_whole_value(
            word_list,
            word_list_len,
            word_index,
            imply_single_unit=imply_single_unit,
        )

    @staticmethod
    def parse_numbers_in_word_list(
        word_list: List[str],
        numbers_use_separator: bool = False,
        numbers_min_value: Optional[int] = None,
        numbers_no_suffix: bool = False,
    ) -> None:
        i = 0
        i_number_prev = -1
        orig_word_list = word_list.copy()
        while i < len(word_list):
            if word_list[i] in from_words_to_digits.valid_digit_words:
                number, suffix, i_next, allow_reformat = from_words_to_digits.parse_number(
                    word_list, i, imply_single_unit=True
                )
                if i != i_next:
                    if numbers_no_suffix and suffix:
                        i += 1
                        continue

                    word_list[i:i_next] = [
                        ("{:,d}".format(int(number)) if (numbers_use_separator and allow_reformat) else number) + suffix
                    ]

                    if (i_number_prev != -1) and (i_number_prev + 1 != i):
                        words_between = tuple(word_list[i_number_prev + 1 : i])
                        found = True
                        # While more could be added here, for now this is enough.
                        if words_between == ("point",):
                            word_list[i_number_prev : i + 1] = [word_list[i_number_prev] + "." + word_list[i]]
                        elif words_between == ("minus",):
                            word_list[i_number_prev : i + 1] = [word_list[i_number_prev] + " - " + word_list[i]]
                        elif words_between == ("plus",):
                            word_list[i_number_prev : i + 1] = [word_list[i_number_prev] + " + " + word_list[i]]
                        elif words_between == ("divided", "by"):
                            word_list[i_number_prev : i + 1] = [word_list[i_number_prev] + " / " + word_list[i]]
                        elif words_between in {("multiplied", "by"), ("times",)}:
                            word_list[i_number_prev : i + 1] = [word_list[i_number_prev] + " * " + word_list[i]]
                        elif words_between == ("modulo",):
                            word_list[i_number_prev : i + 1] = [word_list[i_number_prev] + " % " + word_list[i]]
                        else:
                            found = False

                        if found:
                            i = i_number_prev

                    i_number_prev = i
                    i -= 1
            i += 1

        # Group numbers - recite single digit phone numbers for example.
        # This could be optional, but generally seems handy (good default behavior),
        # e.g. "twenty twenty" -> "2020".
        i = 0
        while i < len(word_list):
            if word_list[i].isdigit() and len(word_list[i]) <= 2:
                j = i + 1
                while j < len(word_list):
                    if word_list[j].isdigit() and len(word_list[j]) <= 2:
                        j += 1
                    else:
                        break
                if i + 1 != j:
                    word_list[i:j] = ["".join(word_list[i:j])]
                    orig_word_list[i:j] = ["".join(orig_word_list[i:j])]
                if numbers_min_value is not None and int(word_list[i]) < numbers_min_value:
                    word_list[i:j] = orig_word_list[i:j]

                i = j
            else:
                i += 1


# -----------------------------------------------------------------------------
# Process Text
#


def process_text_with_user_config(user_config: ModuleType, text: str) -> str:
    process_fn_name = "prism_dictation_process"
    process_fn = getattr(user_config, process_fn_name)
    if process_fn is None:
        sys.stderr.write("User configuration %r has no %r function\n" % (user_config, process_fn_name))
        return text

    try:
        text = process_fn(text)
    except Exception as ex:
        sys.stderr.write("Failed to run %r with error %s\n" % (user_config, str(ex)))
        sys.exit(1)

    if not isinstance(text, str):
        sys.stderr.write("%r returned a %r type, instead of a string\n" % (process_fn_name, type(text)))
        sys.exit(1)

    return text


def process_text(
    text: str,
    *,
    full_sentence: bool = False,
    numbers_as_digits: bool = False,
    numbers_use_separator: bool = False,
    numbers_min_value: Optional[int] = None,
    numbers_no_suffix: bool = False,
) -> str:
    """
    Basic post processing on text.
    Mainly to capitalize words however other kinds of replacements may be supported.
    """

    # Make absolutely sure we never add new lines in text that is typed in.
    # As this will press the return key when using automated key input.
    text = text.replace("\n", " ")
    words = text.split(" ")

    # First parse numbers.
    if numbers_as_digits:
        from_words_to_digits.parse_numbers_in_word_list(
            words,
            numbers_use_separator=numbers_use_separator,
            numbers_min_value=numbers_min_value,
            numbers_no_suffix=numbers_no_suffix,
        )

    # Optional?
    if full_sentence:
        words[0] = words[0].capitalize()
        words[-1] = words[-1]

    return " ".join(words)


# -----------------------------------------------------------------------------
# Text from VOSK
#


def recording_proc_with_non_blocking_stdout(
    input_method: str,
    sample_rate: int,
    pulse_device_name: str,
    # NOTE: typed as a string for Py3.6 compatibility.
) -> "Tuple[subprocess.Popen[bytes], IO[bytes]]":
    if input_method == "PAREC":
        cmd = (
            "parec",
            "--record",
            "--rate=%d" % sample_rate,
            "--channels=1",
            *(("--device=%s" % pulse_device_name,) if pulse_device_name else ()),
            "--format=s16ne",
            "--latency=10",
        )
    elif input_method == "SOX":
        cmd = (
            "sox",
            "-q",
            "-V1",
            "-d",
            "--buffer",
            "1000",
            "-r",
            "%d" % sample_rate,
            "-b",
            "16",
            "-e",
            "signed-integer",
            "-c",
            "1",
            "-t",
            "raw",
            "-L",
            "-",
        )
    else:
        sys.stderr.write("--input %r not supported.\n" % input_method)
        sys.exit(1)

    ps = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    stdout = ps.stdout
    assert stdout is not None

    # Needed so whatever is available can be read (without waiting).
    file_handle_make_non_blocking(stdout)

    return ps, stdout


def text_from_vosk_pipe(
    *,
    vosk_model_dir: str,
    exit_fn: Callable[..., int],
    process_fn: Callable[[str], str],
    handle_fn: Callable[[int, str], None],
    timeout: float,
    idle_time: float,
    progressive: bool,
    progressive_continuous: bool,
    sample_rate: int,
    input_method: str,
    pulse_device_name: str = "",
    suspend_on_start: bool = False,
    verbose: int = 0,
    vosk_grammar_file: str = "",
) -> bool:
    # Delay some imports until recording has started to avoid minor delays.
    import json

    if not os.path.exists(vosk_model_dir):
        sys.stderr.write(
            "Please download the model from "
            "https://alphacephei.com/vosk/models and unpack it to {!r}.\n".format(vosk_model_dir)
        )
        sys.exit(1)

    # NOTE: typed as a string for Py3.6 compatibility.
    def recording_proc_start() -> "Tuple[subprocess.Popen[bytes], IO[bytes]]":
        return recording_proc_with_non_blocking_stdout(input_method, sample_rate, pulse_device_name)

    has_ps = False
    if not suspend_on_start:
        ps, stdout = recording_proc_start()
        has_ps = True

    # `mypy` doesn't know about VOSK.
    import vosk  # type: ignore

    vosk.SetLogLevel(-1)

    if not vosk_grammar_file:
        grammar_json = ""
    else:
        with open(vosk_grammar_file, encoding="utf-8") as fh:
            grammar_json = fh.read()

    # Allow for loading the model to take some time:
    if verbose >= 1:
        sys.stderr.write("Loading model...\n")
    model = vosk.Model(vosk_model_dir)

    if grammar_json == "":
        rec = vosk.KaldiRecognizer(model, sample_rate)
    else:
        rec = vosk.KaldiRecognizer(model, sample_rate, grammar_json)

    if verbose >= 1:
        sys.stderr.write("Model loaded.\n")

    # 1mb
    block_size = 1_048_576

    use_timeout = timeout != 0.0
    if use_timeout:
        timeout_text_prev = ""
        timeout_time_prev = time.time()

    # Collect the output used when time-out is enabled.
    if not (progressive and progressive_continuous):
        text_list: List[str] = []

    # Set true if handle has been called.
    handled_any = False

    if progressive:
        text_prev = ""

    # Track this to prevent excessive load when the "partial" result doesn't change.
    json_text_partial_prev = ""

    # -----------------------------
    # Utilities for Text Processing

    def handle_fn_suspended() -> None:
        nonlocal handled_any
        nonlocal text_prev
        nonlocal json_text_partial_prev

        handled_any = False
        text_prev = ""
        json_text_partial_prev = ""

        if not (progressive and progressive_continuous):
            text_list.clear()

    def handle_fn_wrapper(text: str, is_partial_arg: bool) -> None:
        nonlocal handled_any
        nonlocal text_prev

        # Simple deferred text input, just accumulate values in a list (finish entering text on exit).
        if not progressive:
            if is_partial_arg:
                return
            text_list.append(text)
            handled_any = True
            return

        # Progressive support (type as you speak).
        if progressive_continuous:
            text_curr = process_fn(text)
        else:
            text_curr = process_fn(" ".join(text_list + [text]))

        if text_curr != text_prev:
            match = min(len(text_curr), len(text_prev))
            for i in range(min(len(text_curr), len(text_prev))):
                if text_curr[i] != text_prev[i]:
                    match = i
                    break

            # Emit text, deleting any previous incorrectly transcribed output
            handle_fn(len(text_prev) - match, text_curr[match:])

            text_prev = text_curr

        if not is_partial_arg:
            if progressive_continuous:
                text_prev = ""
            else:
                text_list.append(text)

        handled_any = True

    # -----------------------------------------------
    # Utilities for accessing results on `rec` (VOSK)

    def rec_handle_fn_wrapper_from_final_result() -> str:
        json_text = rec.FinalResult()

        # When `rec.FinalResult()` returns an empty string, typically immediately after a resume,
        # it can cause the JSON decoder to fail. This patch simply ignores that case and continues
        # by returning an empty string to the caller.
        if not json_text:
            return ""

        assert isinstance(json_text, str)
        json_data = json.loads(json_text)
        text = json_data["text"]
        assert isinstance(text, str)
        if text:
            handle_fn_wrapper(text, False)
        return json_text

    def rec_handle_fn_wrapper_from_partial_result(json_text_partial_prev: str) -> Tuple[str, str]:
        json_text = rec.PartialResult()
        # Without this, there are *many* calls with the same partial text.
        if json_text_partial_prev != json_text:
            json_text_partial_prev = json_text

            json_data = json.loads(json_text)
            # In rare cases this can be unset (when resuming from being suspended).
            text = json_data.get("partial", "")
            if text:
                handle_fn_wrapper(text, True)
        return json_text, json_text_partial_prev

    if not suspend_on_start:
        # Support setting up input simulation state.
        handle_fn(SIMULATE_INPUT_CODE_COMMAND, "SETUP")

    # Use code to delay exiting, allowing reading the recording buffer to catch-up.
    code = 0

    # ---------------
    # Signal Handling

    suspend = suspend_on_start

    from types import FrameType

    def do_suspend_pause() -> None:
        nonlocal has_ps, ps, stdout
        rec_handle_fn_wrapper_from_final_result()

        # Don't include any of the current analysis when resuming.
        rec.Reset()

        # Clear the buffer:
        handle_fn_suspended()

        nonlocal verbose
        if verbose >= 1:
            sys.stderr.write("Recording suspended.\n")

        # Close the recording process.
        if has_ps:
            # Support setting up input simulation state.
            handle_fn(SIMULATE_INPUT_CODE_COMMAND, "TEARDOWN")

            stdout.close()
            os.kill(ps.pid, signal.SIGINT)
            del stdout, ps
            has_ps = False

    # Warning: do not call do_suspend_resume() from a signal context because it
    # can cause reentrant runtime errors and other related bugs.
    def do_suspend_resume() -> None:
        nonlocal has_ps, ps, stdout

        # Resume reading from the recording process.
        nonlocal verbose
        if verbose >= 1:
            sys.stderr.write("Recording.\n")

        handle_fn(SIMULATE_INPUT_CODE_COMMAND, "SETUP")
        ps, stdout = recording_proc_start()
        has_ps = True

    def handle_sig_suspend_from_usr1(_signum: int, _frame: Optional[FrameType]) -> None:
        nonlocal suspend
        if suspend:
            return
        suspend = True
        do_suspend_pause()
        # Use when Py3.6 compatibility is dropped.
        # `signal.raise_signal(signal.SIGSTOP)`
        os.kill(os.getpid(), signal.SIGSTOP)

    def handle_sig_resume_from_cont(_signum: int, _frame: Optional[FrameType]) -> None:
        nonlocal suspend
        if not suspend:
            return
        suspend = False

    def handle_sig_reload_from_hup(_signum: int, _frame: Optional[FrameType]) -> None:
        if verbose >= 1:
            sys.stderr.write("Reload.\n")
        process_fn("")

    import signal

    # Suspend resume from separate signals.
    signal.signal(signal.SIGUSR1, handle_sig_suspend_from_usr1)

    # This allows you to stop via ctrl+z and resume with `fg` at a terminal.
    # This intentionally re-uses the handle_sig_suspend_from_usr1 handler:
    signal.signal(signal.SIGTSTP, handle_sig_suspend_from_usr1)

    signal.signal(signal.SIGCONT, handle_sig_resume_from_cont)

    signal.signal(signal.SIGHUP, handle_sig_reload_from_hup)

    if suspend:
        # Use when Py3.6 compatibility is dropped.
        # `signal.raise_signal(signal.SIGSTOP)`
        os.kill(os.getpid(), signal.SIGSTOP)

    # ---------
    # Main Loop

    if idle_time > 0.0:
        idle_time_prev = time.time()

    while code == 0:
        # -1=cancel, 0=continue, 1=finish.
        code = exit_fn(handled_any)

        # Note that when suspend is enabled the entire process is suspended
        # and this look should not run.
        # This check is simply done to prevent any logic running before the process is actually suspended,
        # although in practice it doesn't look to be a problem.
        if suspend:
            continue

        if idle_time > 0.0:
            # Subtract processing time from the previous loop.
            # Skip idling in the event dictation can't keep up with the recording.
            idle_time_curr = time.time()
            idle_time_test = idle_time - (idle_time_curr - idle_time_prev)
            if idle_time_test > 0.0:
                # Prevents excessive processor load.
                time.sleep(idle_time_test)
                idle_time_prev = time.time()
            else:
                idle_time_prev = idle_time_curr

        # Mostly the data read is quite small (under 1k).
        # Only the 1st entry in the loop reads a lot of data due to the time it takes to initialize the VOSK module.
        try:
            data = stdout.read(block_size)
        except (NameError, ValueError):
            # Start recording if `stdout` is not yet open (NameError), or if it
            # was closed via suspend (ValueError).  This can happen either due
            # to a suspend/resume cycle (SIGUSR1/SIGTSTP->SIGCONT) or when
            # --suspend-on-start was specified followed by a SIGCONT.
            do_suspend_resume()
            continue

        if data:
            ok = rec.AcceptWaveform(data)
            if ok:
                json_text_partial_prev = ""
                json_text = rec_handle_fn_wrapper_from_final_result()
            else:
                json_text, json_text_partial_prev = rec_handle_fn_wrapper_from_partial_result(json_text_partial_prev)

            # Monitor the partial output.
            # Finish if no changes are made for `timeout` seconds.
            if use_timeout:
                if json_text != timeout_text_prev:
                    timeout_text_prev = json_text
                    timeout_time_prev = time.time()
                elif time.time() - timeout_time_prev > timeout:
                    if code == 0:
                        code = 1  # The time was exceeded, exit!

    # Close the recording process.
    if has_ps:
        # stdout.close(), no need, this is exiting.
        os.kill(ps.pid, signal.SIGINT)
        del ps, stdout
        has_ps = False

        # Support setting up input simulation state.
        handle_fn(SIMULATE_INPUT_CODE_COMMAND, "TEARDOWN")

    if code == -1:
        sys.stderr.write("Text input canceled!\n")
        sys.exit(0)

    # This writes many JSON blocks, use the last one.
    rec_handle_fn_wrapper_from_final_result()

    if not progressive:
        # We never arrive here needing deletions
        handle_fn(0, process_fn(" ".join(text_list)))

    return handled_any


def main_begin(
    *,
    vosk_model_dir: str,
    path_to_cookie: str = "",
    pulse_device_name: str = "",
    sample_rate: int = 44100,
    input_method: str = "PAREC",
    progressive: bool = False,
    progressive_continuous: bool = False,
    full_sentence: bool = False,
    numbers_as_digits: bool = False,
    numbers_use_separator: bool = False,
    numbers_min_value: Optional[int] = None,
    numbers_no_suffix: bool = False,
    timeout: float = 0.0,
    idle_time: float = 0.0,
    delay_exit: float = 0.0,
    punctuate_from_previous_timeout: float = 0.0,
    config_override: Optional[str],
    output: str = "TYPE",
    simulate_input_tool: str = "XDOTOOL",
    suspend_on_start: bool = False,
    verbose: int = 0,
    vosk_grammar_file: str = "",
) -> None:
    """
    Initialize audio recording, then full text to speech conversion can take place.

    This is terminated by the ``end`` or ``cancel`` actions.
    """

    # Find language model in:
    # - `--vosk-model-dir=...`
    # - `~/.config/prism-dictation/model`
    if not vosk_model_dir:
        vosk_model_dir = calc_user_config_path("model")
        # If this still doesn't exist the error is handled later.

    #
    # Initialize the recording state and perform some sanity checks.
    #
    if not path_to_cookie:
        path_to_cookie = os.path.join(tempfile.gettempdir(), TEMP_COOKIE_NAME)

    is_run_on = False
    if punctuate_from_previous_timeout > 0.0:
        age_in_seconds: Optional[float] = None
        try:
            age_in_seconds = file_age_in_seconds(path_to_cookie)
        except FileNotFoundError:
            age_in_seconds = None
        is_run_on = age_in_seconds is not None and (age_in_seconds < punctuate_from_previous_timeout)
        del age_in_seconds

    # Write the PID, needed for suspend/resume sub-commands to know the PID of the current process.
    with open(path_to_cookie, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))

    # Force zero time-stamp so a fast begin/end (tap) action
    # doesn't leave dictation running.
    touch(path_to_cookie, mtime=0)
    cookie_timestamp = file_mtime_or_none(path_to_cookie)
    if cookie_timestamp != 0:
        sys.stderr.write("Cookie removed after right after creation (unlikely but respect the request)\n")
        return

    #
    # Start recording the output file.
    #

    touch_mtime = None
    use_overtime = delay_exit > 0.0 and timeout == 0.0

    # Lazy loaded so recording can start 1st.
    user_config = None

    def exit_fn(handled_any: bool) -> int:
        nonlocal touch_mtime
        if not os.path.exists(path_to_cookie):
            return -1  # Cancel.
        if file_mtime_or_none(path_to_cookie) != cookie_timestamp:
            # Only delay exit if some text has been handled,
            # this prevents accidental tapping of push to talk from running.
            if handled_any:
                # Implement `delay_exit` workaround.
                if use_overtime:
                    if touch_mtime is None:
                        touch_mtime = time.time()
                    if time.time() - touch_mtime < delay_exit:
                        # Continue until `delay_exit` is reached.
                        return 0
                # End `delay_exit`.

            return 1  # End.
        return 0  # Continue.

    process_fn_is_first = True

    def process_fn(text: str) -> str:
        nonlocal user_config
        nonlocal process_fn_is_first

        #
        # Load the user configuration (when found).
        #
        # text=="" indicates that user_config should be reloaded (SIGHUP)
        #
        if process_fn_is_first or text == "":
            user_config = user_config_as_module_or_none(config_override=config_override, user_config_prev=user_config)

        if not text:
            return ""

        #
        # Simple text post processing and capitalization.
        #
        text = process_text(
            text,
            full_sentence=full_sentence,
            numbers_as_digits=numbers_as_digits,
            numbers_use_separator=numbers_use_separator,
            numbers_min_value=numbers_min_value,
            numbers_no_suffix=numbers_no_suffix,
        )

        #
        # User text post processing (when found).
        #
        if user_config is not None:
            text = process_text_with_user_config(user_config, text)

        if is_run_on:
            # This is a signal that the end of the sentence has been reached.
            if full_sentence:
                text = ". " + text
            else:
                text = ", " + text

        process_fn_is_first = False

        return text

    #
    # Handled the resulting text
    #
    if output == "SIMULATE_INPUT":
        if simulate_input_tool == "XDOTOOL":
            handle_fn = simulate_typing_with_xdotool
        elif simulate_input_tool == "YDOTOOL":
            handle_fn = simulate_typing_with_ydotool
        elif simulate_input_tool == "DOTOOL":
            handle_fn = simulate_typing_with_dotool
        elif simulate_input_tool == "DOTOOLC":
            handle_fn = simulate_typing_with_dotoolc
        elif simulate_input_tool == "WTYPE":
            handle_fn = simulate_typing_with_wtype
        elif simulate_input_tool == "STDOUT":
            handle_fn = simulate_typing_with_stout
        else:
            raise Exception("Internal error, unknown input tool: {!r}".format(simulate_input_tool))

    elif output == "STDOUT":

        def handle_fn(delete_prev_chars: int, text: str) -> None:
            # No setup/tear-down.
            if delete_prev_chars == SIMULATE_INPUT_CODE_COMMAND:
                return

            if delete_prev_chars:
                sys.stdout.write("\x08" * delete_prev_chars)
            sys.stdout.write(text)

    else:
        # Unreachable.
        assert False

    found_any = text_from_vosk_pipe(
        vosk_model_dir=vosk_model_dir,
        pulse_device_name=pulse_device_name,
        sample_rate=sample_rate,
        input_method=input_method,
        timeout=timeout,
        idle_time=idle_time,
        progressive=progressive,
        progressive_continuous=progressive_continuous,
        exit_fn=exit_fn,
        process_fn=process_fn,
        handle_fn=handle_fn,
        suspend_on_start=suspend_on_start,
        verbose=verbose,
        vosk_grammar_file=vosk_grammar_file,
    )

    if not found_any:
        sys.stderr.write("No text found in the audio\n")
        # Avoid continuing punctuation from where this recording (which recorded nothing) left off.
        touch(path_to_cookie)
        return


def main_end(
    *,
    path_to_cookie: str = "",
) -> None:
    if not path_to_cookie:
        path_to_cookie = os.path.join(tempfile.gettempdir(), TEMP_COOKIE_NAME)

    # Resume (does nothing if not suspended), so suspending doesn't prevent the cancel operation.
    main_suspend(path_to_cookie=path_to_cookie, suspend=False, verbose=0)

    touch(path_to_cookie)


def main_cancel(
    *,
    path_to_cookie: str = "",
) -> None:
    if not path_to_cookie:
        path_to_cookie = os.path.join(tempfile.gettempdir(), TEMP_COOKIE_NAME)

    # Resume (does nothing if not suspended), so suspending doesn't prevent the cancel operation.
    main_suspend(path_to_cookie=path_to_cookie, suspend=False, verbose=0)

    file_remove_if_exists(path_to_cookie)


def main_suspend(
    *,
    path_to_cookie: str = "",
    suspend: bool,
    verbose: int,
) -> None:
    import signal

    if not path_to_cookie:
        path_to_cookie = os.path.join(tempfile.gettempdir(), TEMP_COOKIE_NAME)

    if not os.path.exists(path_to_cookie):
        if verbose >= 1:
            sys.stderr.write("No running prism-dictation cookie found at: {:s}, abort!\n".format(path_to_cookie))
        return

    with open(path_to_cookie, "r", encoding="utf-8") as fh:
        data = fh.read()
    try:
        pid = int(data)
    except Exception as ex:
        if verbose >= 1:
            sys.stderr.write("Failed to read PID with error {!r}, abort!\n".format(ex))
        return

    if suspend:
        os.kill(pid, signal.SIGUSR1)
    else:  # Resume.
        os.kill(pid, signal.SIGCONT)


def argparse_generic_command_cookie(subparse: argparse.ArgumentParser) -> None:
    subparse.add_argument(
        "--cookie",
        dest="path_to_cookie",
        default="",
        type=str,
        metavar="FILE_PATH",
        help="Location for writing a temporary cookie (this file is monitored to begin/end dictation).",
        required=False,
    )


def argparse_create_begin(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    subparse = subparsers.add_parser(
        "begin",
        help="Begin dictation.",
        description=(
            "This creates the directory used to store internal data, "
            "so other commands such as sync can be performed."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    argparse_generic_command_cookie(subparse)

    subparse.add_argument(
        "--config",
        default=None,
        dest="config",
        type=str,
        metavar="FILE",
        help=(
            "Override the file used for the user configuration.\n"
            "Use an empty string to prevent the users configuration being read."
        ),
        required=False,
    )

    subparse.add_argument(
        "--vosk-model-dir",
        default="",
        dest="vosk_model_dir",
        type=str,
        metavar="DIR",
        help=("Path to the VOSK model, see: https://alphacephei.com/vosk/models"),
        required=False,
    )

    subparse.add_argument(
        "--vosk-grammar-file",
        default=None,
        dest="vosk_grammar_file",
        type=str,
        metavar="DIR",
        help=(
            "Path to a JSON grammar file.  This restricts the phrases recognized by VOSK for\n"
            "better accuracy.  See `vosk_recognizer_new_grm` in the API reference:\n"
            "https://github.com/alphacep/vosk-api/blob/master/src/vosk_api.h"
        ),
        required=False,
    )

    subparse.add_argument(
        "--pulse-device-name",
        dest="pulse_device_name",
        default="",
        type=str,
        metavar="IDENTIFIER",
        help=(
            "The name of the pulse-audio device to use for recording.\n"
            'See the output of "pactl list sources" to find device names (using the identifier following "Name:").'
        ),
        required=False,
    )

    subparse.add_argument(
        "--sample-rate",
        dest="sample_rate",
        default=44100,
        type=int,
        metavar="HZ",
        help=("The sample rate to use for recording (in Hz).\n" "Defaults to 44100."),
        required=False,
    )

    subparse.add_argument(
        "--defer-output",
        dest="defer_output",
        default=False,
        action="store_true",
        help=(
            "When enabled, output is deferred until exiting.\n"
            "\n"
            "This prevents text being typed during speech (implied with ``--output=STDOUT``)"
        ),
        required=False,
    )

    subparse.add_argument(
        "--continuous",
        dest="progressive_continuous",
        default=False,
        action="store_true",
        help=(
            "Enable this option, when you intend to keep the dictation process enabled for extended periods of time.\n"
            "without this enabled, the entirety of this dictation session will be processed on every update.\n"
            "Only used when ``--defer-output`` is disabled."
        ),
        required=False,
    )

    subparse.add_argument(
        "--timeout",
        dest="timeout",
        default=0.0,
        type=float,
        metavar="SECONDS",
        help=(
            "Time out recording when no speech is processed for the time in seconds.\n"
            "This can be used to avoid having to explicitly exit "
            "(zero disables)."
        ),
        required=False,
    )

    subparse.add_argument(
        "--idle-time",
        dest="idle_time",
        default=0.1,
        type=float,
        metavar="SECONDS",
        help=(
            "Time to idle between processing audio from the recording.\n"
            "Setting to zero is the most responsive at the cost of high CPU usage.\n"
            "The default value is 0.1 (processing 10 times a second), which is quite responsive in practice\n"
            "(the maximum value is clamped to 0.5)"
        ),
        required=False,
    )

    subparse.add_argument(
        "--delay-exit",
        dest="delay_exit",
        default=0.0,
        type=float,
        metavar="SECONDS",
        help=(
            "The time to continue running after an end request.\n"
            'this can be useful so "push to talk" setups can be released while you finish speaking\n'
            "(zero disables)."
        ),
        required=False,
    )

    subparse.add_argument(
        "--suspend-on-start",
        dest="suspend_on_start",
        default=False,
        action="store_true",
        help=(
            "Start the process and immediately suspend.\n"
            "Intended for use when prism-dictation is kept open\n"
            "where resume/suspend is used for dictation instead of begin/end."
        ),
        required=False,
    )

    subparse.add_argument(
        "--punctuate-from-previous-timeout",
        dest="punctuate_from_previous_timeout",
        default=0.0,
        type=float,
        metavar="SECONDS",
        help=(
            "The time-out in seconds for detecting the state of dictation from the previous recording,\n"
            "this can be useful so punctuation it is added before entering the dictation"
            "(zero disables)."
        ),
        required=False,
    )

    subparse.add_argument(
        "--full-sentence",
        dest="full_sentence",
        default=False,
        action="store_true",
        help=(
            "Capitalize the first character.\n"
            "This is also used to add either a comma or a full stop when dictation is performed under the\n"
            "``--punctuate-from-previous-timeout`` value."
        ),
        required=False,
    )

    subparse.add_argument(
        "--numbers-as-digits",
        dest="numbers_as_digits",
        default=False,
        action="store_true",
        help=("Convert numbers into digits instead of using whole words."),
        required=False,
    )

    subparse.add_argument(
        "--numbers-use-separator",
        dest="numbers_use_separator",
        default=False,
        action="store_true",
        help=("Use a comma separators for numbers."),
        required=False,
    )

    subparse.add_argument(
        "--numbers-min-value",
        dest="numbers_min_value",
        default=None,
        type=int,
        help=(
            "Minimum value for numbers to convert from whole words to digits.\n"
            'This provides for more formal writing and prevents terms like "no one"\n'
            'from being turned into "no 1".'
        ),
        required=False,
    )

    subparse.add_argument(
        "--numbers-no-suffix",
        dest="numbers_no_suffix",
        default=False,
        action="store_true",
        help=(
            "Suppress number suffixes when --numbers-as-digits is specified.\n"
            'For example, this will prevent "first" from becoming "1st".'
        ),
        required=False,
    )

    subparse.add_argument(
        "--input",
        dest="input_method",
        default="PAREC",
        type=str,
        metavar="INPUT_METHOD",
        choices=("PAREC", "SOX"),
        help=(
            "Specify input method to be used for audio recording. Valid methods: PAREC, SOX\n"
            "\n"
            "- ``PAREC`` (external command, default)\n"
            "  See --pulse-device-name option to use a specific pulse-audio device.\n"
            "- ``SOX`` (external command)\n"
            "  For help on setting up sox, see ``readme-sox.rst`` in the prism-dictation repository.\n"
        ),
        required=False,
    )

    subparse.add_argument(
        "--output",
        dest="output",
        default="SIMULATE_INPUT",
        choices=("SIMULATE_INPUT", "STDOUT"),
        metavar="OUTPUT_METHOD",
        help=(
            "Method used to at put the result of speech to text.\n"
            "\n"
            "- ``SIMULATE_INPUT`` simulate keystrokes (default).\n"
            "- ``STDOUT`` print the result to the standard output.\n"
            "  Be sure only to handle text from the standard output\n"
            "  as the standard error may be used for reporting any problems that occur.\n"
        ),
        required=False,
    )
    subparse.add_argument(
        "--simulate-input-tool",
        dest="simulate_input_tool",
        default="XDOTOOL",
        choices=("XDOTOOL", "DOTOOL", "DOTOOLC", "YDOTOOL", "WTYPE", "STDOUT"),
        metavar="SIMULATE_INPUT_TOOL",
        help=(
            "Program used to simulate keystrokes (default).\n"
            "\n"
            "- ``XDOTOOL`` Compatible with the X server only (default).\n"
            "- ``DOTOOL`` Compatible with all Linux distributions and Wayland.\n"
            "- ``DOTOOLC`` Same as DOTOOL but for use with the `dotoold` daemon.\n"
            "- ``YDOTOOL`` Compatible with all Linux distributions and Wayland but requires some setup.\n"
            "- ``WTYPE`` Compatible with Wayland.\n"
            "- ``STDOUT`` Bare stdout with Ctrl-H for backspaces.\n"
            "  For help on setting up ydotool, see ``readme-ydotool.rst`` in the prism-dictation repository.\n"
        ),
        required=False,
    )

    subparse.add_argument(
        "--verbose",
        dest="verbose",
        default=0,
        type=int,
        help=(
            "Verbosity level, defaults to zero (no output except for errors)\n"
            "\n"
            "- Level 1: report top level actions (dictation started, suspended .. etc).\n"
            "- Level 2: report internal details (may be noisy)."
        ),
        required=False,
    )

    subparse.add_argument(
        "-",
        dest="rest",
        default=False,
        nargs=argparse.REMAINDER,
        help=(
            "End argument parsing.\n"
            "This can be used for user defined arguments which configuration scripts may read from the ``sys.argv``."
        ),
    )

    subparse.set_defaults(
        func=lambda args: main_begin(
            path_to_cookie=args.path_to_cookie,
            vosk_model_dir=args.vosk_model_dir,
            pulse_device_name=args.pulse_device_name,
            sample_rate=args.sample_rate,
            input_method=args.input_method,
            progressive=not (args.defer_output or args.output == "STDOUT"),
            progressive_continuous=args.progressive_continuous,
            full_sentence=args.full_sentence,
            numbers_as_digits=args.numbers_as_digits,
            numbers_use_separator=args.numbers_use_separator,
            numbers_min_value=args.numbers_min_value,
            numbers_no_suffix=args.numbers_no_suffix,
            timeout=args.timeout,
            idle_time=min(args.idle_time, 0.5),
            delay_exit=args.delay_exit,
            punctuate_from_previous_timeout=args.punctuate_from_previous_timeout,
            config_override=args.config,
            output=args.output,
            simulate_input_tool=args.simulate_input_tool,
            suspend_on_start=args.suspend_on_start,
            verbose=args.verbose,
            vosk_grammar_file=args.vosk_grammar_file,
        ),
    )


def argparse_create_end(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    subparse = subparsers.add_parser(
        "end",
        help="End dictation.",
        description="""\
This ends dictation, causing the text to be typed in.
    """,
        formatter_class=argparse.RawTextHelpFormatter,
    )

    argparse_generic_command_cookie(subparse)

    subparse.set_defaults(
        func=lambda args: main_end(
            path_to_cookie=args.path_to_cookie,
        ),
    )


def argparse_create_cancel(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    subparse = subparsers.add_parser(
        "cancel",
        help="Cancel dictation.",
        description="This cancels dictation.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    argparse_generic_command_cookie(subparse)

    subparse.set_defaults(
        func=lambda args: main_cancel(
            path_to_cookie=args.path_to_cookie,
        ),
    )


def argparse_create_suspend(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    subparse = subparsers.add_parser(
        "suspend",
        help="Suspend the dictation process.",
        description=(
            "Suspend recording audio & the dictation process.\n"
            "\n"
            "This is useful on slower systems or when large language models take longer to load.\n"
            "Recording audio is stopped and the process is paused to remove any CPU overhead."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    argparse_generic_command_cookie(subparse)

    subparse.set_defaults(
        func=lambda args: main_suspend(
            path_to_cookie=args.path_to_cookie,
            suspend=True,
            verbose=1,
        ),
    )


def argparse_create_resume(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    subparse = subparsers.add_parser(
        "resume",
        help="Resume the dictation process.",
        description=(
            "Resume recording audio & the dictation process.\n"
            "\n"
            "This is to be used to resume after the 'suspend' command.\n"
            "When prism-dictation is not suspended, this does nothing.\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    argparse_generic_command_cookie(subparse)

    subparse.set_defaults(
        func=lambda args: main_suspend(
            path_to_cookie=args.path_to_cookie,
            suspend=False,
            verbose=1,
        ),
    )


def argparse_create() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)

    subparsers = parser.add_subparsers()

    argparse_create_begin(subparsers)

    argparse_create_end(subparsers)
    argparse_create_cancel(subparsers)

    argparse_create_suspend(subparsers)
    argparse_create_resume(subparsers)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse_create()
    args = parser.parse_args(argv)
    # Call sub-parser callback.
    if not hasattr(args, "func"):
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
