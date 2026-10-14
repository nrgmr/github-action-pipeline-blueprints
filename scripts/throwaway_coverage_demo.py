"""Throwaway module for the coverage gate demo. Half of it is tested on purpose."""


def covered(value: int) -> int:
    doubled = value * 2
    return doubled + 1


def uncovered(value: int) -> int:
    tripled = value * 3
    return tripled + 1
