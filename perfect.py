import time


def lucas_lehmer(p):
    """Executes the Lucas-Lehmer test for 2^p - 1 using fast bitwise modulo."""
    if p == 2:
        return True

    m = (1 << p) - 1
    s = 4

    # Optimization: A fast bitwise trick for modulo (x % (2^p - 1))
    # This avoids slow hardware division entirely.
    for _ in range(p - 2):
        sq = s * s
        # (sq & m) is the remainder, (sq >> p) is the quotient
        s = (sq & m) + (sq >> p)
        if s >= m:
            s -= m
        s -= 2

    return s == 0


def is_prime_exponent(p):
    """Fast wheel-sieve primality test for the small exponent p."""
    if p < 2:
        return False
    if p == 2 or p == 3:
        return True
    if p % 2 == 0 or p % 3 == 0:
        return False
    i = 5
    while i * i <= p:
        if p % i == 0 or p % (i + 2) == 0:
            return False
        i += 6
    return True


def main():
    # Adjusted to 10^10000 (Goes up to exponent p ≈ 1661)
    max_limit = 10**10000

    print(
        f"Searching up to 10^10000 using Infinite-Precision Bitwise Lucas-Lehmer..."
    )
    start_time = time.time()

    perfect_numbers = []

    # p=1661 generates a perfect number close to 10^1000.
    # Let's search up to p=2000 to find all valid ones within your limit.
    for p in range(2, 20000):
        if is_prime_exponent(p):
            if lucas_lehmer(p):
                # Perfect number formula using fast bit-shifts: (2^(p-1)) * (2^p - 1)
                perfect_number = (1 << (p - 1)) * ((1 << p) - 1)

                if perfect_number <= max_limit:
                    perfect_numbers.append((p, perfect_number))
                else:
                    break

    # Print results safely
    print("\nPerfect Numbers Found (Showing Exponent 'p' and Digit Count):")
    for p, num in perfect_numbers:
        digit_count = len(str(num))
        # We print the full number only for the smaller ones to avoid freezing your terminal
        if digit_count < 50:
            print(f"p={p}: {num:,} ({digit_count} digits)")
        else:
            print(
                f"p={p}: [Massive Number starting with {str(num)[:10]}...] ({digit_count} digits)"
            )

    end_time = time.time()
    print(f"\nFinished in {end_time - start_time:.6f} seconds!")


if __name__ == "__main__":
    main()
