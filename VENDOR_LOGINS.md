# Vendor demo logins

The five accounts wired into this prototype. Nothing on the sign-in page reveals them — enter the
mobile, then the OTP. Codes are fixed because there is no SMS gateway here; `vi/auth.py` holds them
and `tests/test_auth.py` fails if this file drifts out of sync with it.

| Vendor | Archetype | Mobile | OTP | What the record shows |
| --- | --- | --- | --- | --- |
| Shakti Enterprises | V-STAR | 9810000001 | 111111 | the healthy record — high participation, 95% on-time |
| Rathi Metallurgicals Pvt Ltd | V-LATE | 9810000002 | 222222 | misses ~82% of counter-offer windows |
| Omkar Industrial Supplies | V-HIGH | 9810000003 | 333333 | 7–10% above L1 in Steel, no wins there |
| Kaveri Chem & Spares | V-TECHWEAK | 9810000004 | 444444 | L1 on price, fails on quality certifications |
| Meridian Freight & Pack | V-SLIPPING | 9810000005 | 555555 | delivery sliding over the last six months |

`+91`, a leading `0` and spacing are all accepted — `+91 98100-00001` is the same number as `9810000001`.

A session is one vendor. To look at another record, **Sign out** and sign in with a different number.

These are synthetic accounts against synthetic data; they are demo credentials, not secrets. Real
vendor auth on Procol is the SMS gateway, and `ACCOUNTS` in `vi/auth.py` is the seam where it plugs in.
