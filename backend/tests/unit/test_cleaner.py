from documind.ingestion.cleaner import collapse_whitespace, normalize_page_text, remove_repeated_lines

NBSP, SOFT_HYPHEN, FI_LIGATURE, FF_LIGATURE = chr(0xA0), chr(0xAD), chr(0xFB01), chr(0xFB00)


def test_ligatures_and_full_width_forms_are_folded():
    full_width_abc = "".join(chr(0xFF21 + i) for i in range(3))
    assert normalize_page_text(f"{FI_LIGATURE}nal e{FF_LIGATURE}ort {full_width_abc}") == "final effort ABC"


def test_line_break_hyphenation_is_joined_between_lowercase_letters():
    assert normalize_page_text("distri-\nbuted systems") == "distributed systems"


def test_hyphen_before_uppercase_is_kept():
    assert normalize_page_text("Multi-\nPaxos") == "Multi-\nPaxos"


def test_soft_hyphens_and_control_characters_are_removed():
    assert normalize_page_text(f"con{SOFT_HYPHEN}sensus\x00 log\x07") == "consensus log"


def test_whitespace_is_collapsed_and_blank_lines_dropped():
    raw = f"  first   line \t\n\n\n second{NBSP}{NBSP}line  \r\n"
    assert normalize_page_text(raw) == "first line\nsecond line"


def test_empty_input():
    assert normalize_page_text("") == ""
    assert normalize_page_text(" \n\t ") == ""


def test_collapse_whitespace():
    assert collapse_whitespace("a\n b\t\tc ") == "a b c"


def test_repeated_headers_footers_and_page_numbers_are_removed():
    pages = [f"ACME Corp report\nPage {i}\nUnique content of page {i} about topic {i}." for i in range(1, 6)]
    cleaned = remove_repeated_lines(pages)
    assert cleaned[2] == "Unique content of page 3 about topic 3."


def test_short_documents_and_long_repeated_lines_are_kept():
    two_pages = ["Header\nA", "Header\nB"]
    assert remove_repeated_lines(two_pages) == two_pages
    sentence = "This long sentence repeats on every page because the author copied it everywhere for emphasis."
    pages = [f"{sentence}\nBody text for section {i} with more details." for i in range(4)]
    assert remove_repeated_lines(pages) == pages


def test_blank_pages_do_not_count_towards_repetition():
    pages = ["Header\nA", "", "", "", "Header\nB"]
    assert remove_repeated_lines(pages) == pages


def test_content_lines_that_differ_only_in_numbers_are_kept():
    pages = [f"Header\nRevenue in {2020 + i} was DKK {40 + i} million in total" for i in range(4)]
    assert remove_repeated_lines(pages) == [f"Revenue in {2020 + i} was DKK {40 + i} million in total" for i in range(4)]
