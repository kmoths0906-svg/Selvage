"""Market-intelligence layer: scanners, catalysts, macro, scoring.

This package only ever *proposes* candidates and evidence. It never calls
into papertrader.broker_sim directly -- intel_engine.py is the sole place
where a scored candidate can become an actual paper trade, and it does so
by calling the existing, already-tested papertrader risk/broker_sim/
portfolio/journal code, not a reimplementation of it.
"""
