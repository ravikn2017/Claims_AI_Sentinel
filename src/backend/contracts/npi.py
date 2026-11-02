"""CMS NPI check digit: Luhn over the prefix 80840 plus the full 10-digit NPI."""


def npi_is_valid(npi: str) -> bool:
    if len(npi) != 10 or not npi.isdigit():
        return False
    digits = [int(character) for character in "80840" + npi]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
