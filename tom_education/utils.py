def assert_valid_suffix(filename, allowed_suffixes):
    """
    Check that `filename` has one of the strings in `allowed_suffixes` as a
    suffix. Raises an AssertionError if not.
    """
    if not any(filename.endswith(suffix) for suffix in allowed_suffixes):
        err_msg = (
            "File '{}' does not end an allowed filename suffix ({})"
            .format(filename, ', '.join(allowed_suffixes))
        )
        raise AssertionError(err_msg)
