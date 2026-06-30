#!/usr/bin/env python3
"""
tcp_regime_sim.py - TCP OptiFlow Emulation & Analysis Software
A professional web-based dashboard and analysis tool.

This script runs a web-based dashboard on port 5000. It performs a Taguchi L9
orthogonal array experiment to analyze TCP Reno, Cubic, and BBR congestion
control under various bandwidth and delay conditions.

If run on Linux as root with Mininet installed, it executes a physical emulation.
Otherwise, it enters 'Mock Mode' to simulate the physical results using realistic
TCP performance models, allowing full software testing on Windows/macOS.
"""

import os
import sys
import json
import time
import math
import csv
import threading
import subprocess
from flask import Flask, jsonify, request, Response, send_file

# Initialize Flask app
app = Flask(__name__)

# Global state and thread safety locks
state_lock = threading.Lock()
log_lock = threading.Lock()
is_running = False
log_queue = []
latest_results = []
main_effects = {}
sim_mode = "Unknown"  # "Physical Emulation (Mininet)" or "Physical Mock (Windows/No Root)"

# Taguchi L9 Orthogonal Array Design
# Factors:
# 1. TCP Algorithm (A): Reno, Cubic, BBR
# 2. Bandwidth (B): 100 Mbps, 500 Mbps, 1000 Mbps
# 3. Delay (C): 10 ms, 50 ms, 100 ms
L9_MATRIX = [
    {"run": 1, "algo": "reno",  "bw": 100,  "delay": 10},
    {"run": 2, "algo": "reno",  "bw": 500,  "delay": 50},
    {"run": 3, "algo": "reno",  "bw": 1000, "delay": 100},
    {"run": 4, "algo": "cubic", "bw": 100,  "delay": 50},
    {"run": 5, "algo": "cubic", "bw": 500,  "delay": 100},
    {"run": 6, "algo": "cubic", "bw": 1000, "delay": 10},
    {"run": 7, "algo": "bbr",   "bw": 100,  "delay": 100},
    {"run": 8, "algo": "bbr",   "bw": 500,  "delay": 10},
    {"run": 9, "algo": "bbr",   "bw": 1000, "delay": 50}
]

CSV_FILENAME = "tcp_regime_results.csv"

def log_message(text, log_type="info"):
    """Appends a log message with a timestamp and type to the shared queue."""
    timestamp = time.strftime("%H:%M:%S")
    with log_lock:
        log_queue.append({"time": timestamp, "text": text, "type": log_type})
    print(f"[{timestamp}] [{log_type.upper()}] {text}")

def check_mininet_available():
    """Checks if Mininet and root privileges are available."""
    if os.name != 'posix':
        return False, "Non-Linux OS detected (Windows/macOS)"
    if os.geteuid() != 0:
        return False, "Insufficient privileges (must run as root/sudo)"
    try:
        import mininet
        return True, "Mininet and root privileges available"
    except ImportError:
        return False, "Mininet Python library not installed"

# Detect simulation mode
has_mininet, mode_reason = check_mininet_available()
sim_mode = "Physical Emulation (Mininet)" if has_mininet else "Physical Mock (Windows/No Root)"

# ==========================================
# 1. Physics-Based Mock Emulation Engine
# ==========================================
def run_mock_trial(run_id, algo, bw, delay):
    """
    Simulates a TCP test run using mathematical models of TCP performance
    under high-speed, high-latency (high BDP) networks.
    """
    log_message(f"Initiating Mock Link: Bandwidth = {bw} Mbps, Delay = {delay} ms...", "info")
    time.sleep(0.3)
    log_message(f"Configuring TCP Congestion Control to '{algo.upper()}' on h1...", "info")
    time.sleep(0.2)
    log_message(f"Running iperf3 client on h1 -> h2 (10 seconds)...", "info")
    
    # Calculate Bandwidth-Delay Product (BDP) in Megabits
    # BDP = Bandwidth (Mbps) * Round Trip Time (RTT). RTT is roughly 2 * delay.
    rtt = 2 * delay / 1000.0  # seconds
    bdp = bw * rtt            # Megabits
    
    # Mathematical models representing physical TCP behaviors:
    # - Reno: Highly sensitive to BDP. AIMD recovery takes too long on high BDP.
    # - Cubic: Window growth is cubic, much better than Reno, but still suffers under very high BDP and packet loss.
    # - BBR: Model-based. Ignores packet loss, estimates max bandwidth and min RTT. Fills the pipe efficiently.
    
    if algo == "reno":
        # Reno efficiency degrades rapidly as BDP increases
        efficiency = 0.92 / (1.0 + 0.004 * (bdp ** 0.65))
        loss_factor = 0.001 * (bdp ** 0.5)
        # Higher coefficient of variation (unstable)
        cv = 0.14 + 0.0005 * bdp
    elif algo == "cubic":
        # Cubic is more resilient than Reno
        efficiency = 0.95 / (1.0 + 0.0009 * (bdp ** 0.5))
        loss_factor = 0.0004 * (bdp ** 0.4)
        cv = 0.07 + 0.0002 * bdp
    else:  # bbr
        # BBR maintains near-line rate efficiency across BDP scales
        efficiency = 0.98 / (1.0 + 0.00005 * (bdp ** 0.3))
        loss_factor = 0.00002 * (bdp ** 0.3)
        cv = 0.025  # Highly stable pacing
        
    # Cap efficiency between 5% and 98%
    efficiency = max(0.05, min(0.98, efficiency))
    
    # Calculate average throughput
    avg_throughput = bw * efficiency
    
    # Generate 10 one-second intervals with realistic random fluctuations
    import numpy as np
    intervals = []
    total_bytes = 0
    mss = 1448  # standard TCP MSS
    
    for sec in range(10):
        # Generate random fluctuation based on TCP stability (cv)
        # Using simple random module to avoid heavy numpy dependency if not available,
        # but numpy is listed in requirements. Let's write a simple fallback.
        try:
            fluc = np.random.normal(1.0, cv)
        except:
            import random
            fluc = random.gauss(1.0, cv)
            
        fluc = max(0.1, fluc)  # prevent negative throughput
        int_thr = avg_throughput * fluc
        # Ensure interval throughput doesn't exceed link capacity
        int_thr = min(bw * 0.99, int_thr)
        
        int_bytes = int((int_thr * 1e6) / 8.0) # bytes sent in 1s
        total_bytes += int_bytes
        intervals.append(int_thr)
        
        # Log interval to simulate real iperf3 output
        log_message(f"[  5]  {sec:2d}.00-{sec+1:2d}.00  sec  {int_bytes/(1024*1024):.2f} MBytes  {int_thr:.2f} Mbits/sec", "iperf")
        time.sleep(0.1)  # brief sleep to simulate real-time scrolling
        
    # Calculate responses
    final_throughput = sum(intervals) / len(intervals)
    
    # Variance of the intervals (stability)
    mean_thr = sum(intervals) / len(intervals)
    variance = sum((x - mean_thr) ** 2 for x in intervals) / len(intervals)
    
    # Calculate Retransmissions
    # Reno and Cubic trigger retransmissions based on window drops. BBR keeps them very low.
    total_packets = total_bytes / mss
    retrans_rate = loss_factor * 100.0  # percentage
    retransmits = int(total_packets * loss_factor)
    if retransmits < 0:
        retransmits = 0
        
    log_message(f"- - - - - - - - - - - - - - - - - - - - - - - - - - - - - -", "info")
    log_message(f"Trial Results: Throughput = {final_throughput:.2f} Mbps, Variance = {variance:.2f}, Retransmissions = {retransmits} ({retrans_rate:.4f}%)", "success")
    
    return {
        "run": run_id,
        "algo": algo,
        "bw": bw,
        "delay": delay,
        "throughput": round(final_throughput, 2),
        "variance": round(variance, 4),
        "retrans_rate": round(retrans_rate, 4),
        "retransmits": retransmits
    }

# ==========================================
# 2. Mininet Physical Emulation Engine
# ==========================================
def run_mininet_trial(run_id, algo, bw, delay):
    """
    Executes a physical network emulation using Mininet.
    Creates a topology: Host 1 <-> Switch <-> Host 2
    Applies bandwidth and delay constraints via TCLink.
    Generates TCP traffic using iperf3 and parses JSON results.
    """
    log_message(f"Initializing Mininet Topology for Run {run_id}...", "info")
    
    # Import Mininet locally to prevent startup crashes on Windows
    from mininet.net import Mininet
    from mininet.node import OVSController
    from mininet.link import TCLink
    from mininet.clean import cleanup
    
    # Clean up any previous stale Mininet runs
    cleanup()
    
    net = Mininet(controller=OVSController, link=TCLink)
    
    log_message("Adding Controller and Hosts (h1, h2)...", "info")
    net.addController('c0')
    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    
    log_message(f"Configuring Bottleneck Link: Bandwidth = {bw} Mbps, Delay = {delay} ms...", "info")
    # Apply constraints on the link
    net.addLink(h1, h2, cls=TCLink, bw=bw, delay=f"{delay}ms")
    
    log_message("Starting Mininet network...", "info")
    net.start()
    
    log_message("Waiting for network convergence...", "info")
    time.sleep(1)
    
    log_message("Starting iperf3 server on h2...", "info")
    # Start iperf3 server in daemon mode on h2
    h2.cmd('iperf3 -s -D')
    time.sleep(1)
    
    log_message(f"Running iperf3 client on h1 with TCP {algo.upper()}...", "info")
    # Run iperf3 client on h1, outputting JSON
    cmd = f'iperf3 -c 10.0.0.2 -C {algo} -t 10 -i 1 -J'
    log_message(f"h1 cmd: {cmd}", "info")
    
    # Execute command and capture output
    raw_output = h1.cmd(cmd)
    
    # Stop Mininet and clean up
    log_message("Stopping Mininet network...", "info")
    net.stop()
    cleanup()
    
    # Parse JSON results
    try:
        data = json.loads(raw_output)
        
        # Stream interval data to the UI log
        intervals_data = data.get("intervals", [])
        interval_throughputs = []
        
        for idx, interval in enumerate(intervals_data):
            sum_info = interval.get("sum", {})
            bps = sum_info.get("bits_per_second", 0)
            mbps = bps / 1e6
            interval_throughputs.append(mbps)
            
            bytes_sent = sum_info.get("bytes", 0)
            retr = sum_info.get("retransmits", 0)
            
            log_message(f"[  5]  {idx:2d}.00-{idx+1:2d}.00  sec  {bytes_sent/(1024*1024):.2f} MBytes  {mbps:.2f} Mbits/sec  {retr} retrans", "iperf")
            
        # Extract end summaries
        end_info = data.get("end", {})
        sum_received = end_info.get("sum_received", {})
        sum_sent = end_info.get("sum_sent", {})
        
        # 1. Throughput (Mbps)
        bps_received = sum_received.get("bits_per_second", 0)
        final_throughput = bps_received / 1e6
        
        # 2. Throughput Variance (stability)
        if interval_throughputs:
            mean_thr = sum(interval_throughputs) / len(interval_throughputs)
            variance = sum((x - mean_thr) ** 2 for x in interval_throughputs) / len(interval_throughputs)
        else:
            variance = 0.0
            
        # 3. Retransmission Rate (%)
        retransmits = sum_sent.get("retransmits", 0)
        total_bytes = sum_sent.get("bytes", 0)
        
        # Try to find MSS from first interval stream tcp_info
        mss = 1448
        try:
            streams = intervals_data[0].get("streams", [])
            if streams:
                mss = streams[0].get("snd_mss", 1448)
        except:
            pass
            
        total_packets = total_bytes / mss
        retrans_rate = (retransmits / total_packets * 100.0) if total_packets > 0 else 0.0
        
        log_message(f"- - - - - - - - - - - - - - - - - - - - - - - - - - - - - -", "info")
        log_message(f"Trial Results: Throughput = {final_throughput:.2f} Mbps, Variance = {variance:.2f}, Retransmissions = {retransmits} ({retrans_rate:.4f}%)", "success")
        
        return {
            "run": run_id,
            "algo": algo,
            "bw": bw,
            "delay": delay,
            "throughput": round(final_throughput, 2),
            "variance": round(variance, 4),
            "retrans_rate": round(retrans_rate, 4),
            "retransmits": retransmits
        }
        
    except Exception as e:
        log_message(f"Failed to parse iperf3 JSON output: {str(e)}", "error")
        log_message("Raw output snippet:", "error")
        log_message(raw_output[:500] + "...", "error")
        
        # Fallback to zero values to prevent crash
        return {
            "run": run_id,
            "algo": algo,
            "bw": bw,
            "delay": delay,
            "throughput": 0.0,
            "variance": 0.0,
            "retrans_rate": 0.0,
            "retransmits": 0
        }

# ==========================================
# 3. Taguchi Analysis Calculations
# ==========================================
def compute_taguchi_analysis(results_list):
    """
    Computes the Main Effects for the L9 Orthogonal Array.
    Calculates the average Throughput, Variance, and Retransmission Rate
    for each level of the three factors.
    """
    if not results_list:
        return {}
        
    import pandas as pd
    df = pd.DataFrame(results_list)
    
    factors = {
        "algo": ["reno", "cubic", "bbr"],
        "bw": [100, 500, 1000],
        "delay": [10, 50, 100]
    }
    
    analysis = {}
    
    for factor, levels in factors.items():
        analysis[factor] = {}
        for lvl in levels:
            # Filter results for this specific factor level
            filtered_df = df[df[factor] == lvl]
            
            analysis[factor][str(lvl)] = {
                "throughput": round(float(filtered_df["throughput"].mean()), 2),
                "variance": round(float(filtered_df["variance"].mean()), 4),
                "retrans_rate": round(float(filtered_df["retrans_rate"].mean()), 4)
            }
            
    return analysis

# ==========================================
# 4. Simulation Control Thread
# ==========================================
def run_simulation_sequence():
    """Background thread that executes the L9 experiment sequence."""
    global is_running, latest_results, main_effects
    
    with state_lock:
        is_running = True
        log_queue.clear()
        latest_results = []
        main_effects = {}
        
    log_message("Starting TCP OptiFlow Congestion Regime Simulation...", "info")
    log_message(f"Environment Mode: {sim_mode}", "info")
    log_message("Taguchi L9 Orthogonal Array loaded (9 Experimental Runs).", "info")
    
    start_time = time.time()
    
    for run_config in L9_MATRIX:
        run_id = run_config["run"]
        algo = run_config["algo"]
        bw = run_config["bw"]
        delay = run_config["delay"]
        
        log_message(f"=========================================", "info")
        log_message(f"RUN {run_id}/9: TCP={algo.upper()} | BW={bw}Mbps | Delay={delay}ms", "info")
        log_message(f"=========================================", "info")
        
        if has_mininet:
            res = run_mininet_trial(run_id, algo, bw, delay)
        else:
            res = run_mock_trial(run_id, algo, bw, delay)
            
        latest_results.append(res)
        
    # Write to CSV
    try:
        with open(CSV_FILENAME, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Run", "TCP_Algorithm", "Bandwidth_Mbps", "Delay_ms", "Throughput_Mbps", "Throughput_Variance", "Retransmission_Rate_Pct", "Retransmits"])
            for r in latest_results:
                writer.writerow([
                    r["run"], r["algo"], r["bw"], r["delay"],
                    r["throughput"], r["variance"], r["retrans_rate"], r["retransmits"]
                ])
        log_message(f"Successfully exported data to {CSV_FILENAME}", "success")
    except Exception as e:
        log_message(f"Failed to export CSV: {str(e)}", "error")
        
    # Perform Taguchi calculations
    try:
        main_effects = compute_taguchi_analysis(latest_results)
        log_message("Taguchi L9 Main Effects analysis completed successfully.", "success")
    except Exception as e:
        log_message(f"Taguchi analysis failed: {str(e)}", "error")
        
    elapsed = time.time() - start_time
    log_message(f"Simulation completed in {elapsed:.2f} seconds.", "success")
    
    with state_lock:
        is_running = False

# ==========================================
# 5. Flask Web Routes
# ==========================================
@app.route("/")
def index():
    """Serves the main dashboard user interface."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TCP OptiFlow - Congestion Control Analyzer [PRTS_v2.4]</title>
    <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;500;600;700&family=Share+Tech&family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            /* Arknights Color Palette with the requested Purple-to-Orange Gradient */
            --bg-main: #07050b;
            --bg-card: rgba(14, 11, 22, 0.9);
            --bg-card-header: #151121;
            --border-color: rgba(127, 90, 240, 0.3);
            --border-glow: rgba(127, 90, 240, 0.6);
            
            --primary: #7f5af0;       /* Muted Purple */
            --accent: #ff9f43;        /* Glowing Gold/Orange */
            
            --text-main: #e6e4eb;
            --text-muted: #746f88;
            --text-success: #00ffbc;
            --text-error: #ff4d4d;
            --terminal-bg: #030205;
            
            --font-title: 'Share Tech', sans-serif;
            --font-condensed: 'Barlow Condensed', sans-serif;
            --font-sans: 'Inter', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: var(--font-sans);
            background-color: var(--bg-main);
            /* Dotted Grid Pattern for Tactical Monitor Feel */
            background-image: 
                radial-gradient(rgba(127, 90, 240, 0.08) 1px, transparent 1px),
                linear-gradient(135deg, #07050b 0%, #110e1a 100%);
            background-size: 24px 24px, 100% 100%;
            background-attachment: fixed;
            color: var(--text-main);
            min-height: 100vh;
            line-height: 1.4;
            padding: 2rem;
        }

        .container {
            max-width: 1280px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }

        /* Arknights Tactical Header */
        .app-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            padding-bottom: 1rem;
            border-bottom: 2px solid var(--primary);
            position: relative;
        }

        .app-header::after {
            content: '';
            position: absolute;
            bottom: -2px;
            right: 0;
            width: 120px;
            height: 6px;
            background-color: var(--accent);
        }

        .header-brand {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .brand-title {
            font-family: var(--font-title);
            font-size: 2rem;
            font-weight: 400;
            letter-spacing: 3px;
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .brand-title span.accent-glow {
            color: var(--accent);
            text-shadow: 0 0 8px rgba(255, 159, 67, 0.4);
        }

        .brand-sub {
            font-family: var(--font-condensed);
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-muted);
            letter-spacing: 2px;
            text-transform: uppercase;
        }

        .status-panel {
            font-family: var(--font-mono);
            font-size: 0.75rem;
            text-align: right;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .status-line {
            display: flex;
            justify-content: flex-end;
            gap: 8px;
        }

        .status-label {
            color: var(--text-muted);
        }

        .status-value {
            color: var(--text-main);
            font-weight: 700;
        }

        .status-value.active {
            color: var(--accent);
            text-shadow: 0 0 5px rgba(255, 159, 67, 0.3);
        }

        /* Layout Grid */
        .layout-grid {
            display: grid;
            grid-template-columns: 1fr 1.3fr;
            gap: 1.5rem;
        }

        @media (max-width: 960px) {
            .layout-grid {
                grid-template-columns: 1fr;
            }
        }

        /* Tactical Beveled Cards */
        .card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            position: relative;
            display: flex;
            flex-direction: column;
            /* Beveled bottom-right corner */
            clip-path: polygon(0 0, 100% 0, 100% calc(100% - 12px), calc(100% - 12px) 100%, 0 100%);
        }

        .card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 2px;
            background: linear-gradient(90deg, var(--primary), transparent);
        }

        .card-header {
            padding: 1rem 1.25rem;
            background-color: var(--bg-card-header);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .card-title {
            font-family: var(--font-title);
            font-size: 1.1rem;
            letter-spacing: 1px;
            color: #ffffff;
            text-transform: uppercase;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .card-title::before {
            content: '//';
            color: var(--accent);
            font-weight: 700;
        }

        .card-code {
            font-family: var(--font-mono);
            font-size: 0.7rem;
            color: var(--text-muted);
            border: 1px solid rgba(127, 90, 240, 0.2);
            padding: 2px 6px;
        }

        /* Config Card Details */
        .card-body {
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
            flex-grow: 1;
        }

        .factor-group {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .factor-row {
            display: flex;
            flex-direction: column;
            gap: 6px;
            padding-bottom: 1rem;
            border-bottom: 1px solid rgba(127, 90, 240, 0.1);
        }

        .factor-row:last-child {
            padding-bottom: 0;
            border-bottom: none;
        }

        .factor-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
        }

        .factor-label {
            font-family: var(--font-condensed);
            font-size: 0.95rem;
            font-weight: 600;
            letter-spacing: 1px;
            color: var(--text-main);
            text-transform: uppercase;
        }

        .factor-desc {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .factor-badges {
            display: flex;
            gap: 8px;
            margin-top: 4px;
        }

        .badge {
            background-color: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(127, 90, 240, 0.2);
            color: var(--text-muted);
            padding: 0.35rem 0.75rem;
            font-size: 0.8rem;
            font-family: var(--font-mono);
            font-weight: 500;
            flex-grow: 1;
            text-align: center;
            position: relative;
        }

        /* Tactical active indicator for badges */
        .badge.active {
            background-color: rgba(127, 90, 240, 0.15);
            border-color: var(--primary);
            color: #ffffff;
        }

        .badge.active::after {
            content: '';
            position: absolute;
            bottom: 0;
            right: 0;
            width: 4px;
            height: 4px;
            background-color: var(--accent);
        }

        /* Tactical Button */
        .btn-primary {
            background: linear-gradient(90deg, var(--primary) 0%, #6c5ce7 100%);
            color: #ffffff;
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 1rem;
            font-family: var(--font-condensed);
            font-size: 1.1rem;
            font-weight: 700;
            letter-spacing: 2px;
            text-transform: uppercase;
            cursor: pointer;
            transition: all 0.2s ease;
            clip-path: polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 12px 100%, 0 calc(100% - 12px));
            width: 100%;
            margin-top: auto;
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
        }

        .btn-primary:hover:not(:disabled) {
            background: var(--accent);
            color: var(--bg-main);
            border-color: var(--accent);
            font-weight: 800;
        }

        .btn-primary:disabled {
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-muted);
            border-color: var(--border-color);
            cursor: not-allowed;
            clip-path: none;
        }

        .btn-secondary {
            background: transparent;
            border: 1px solid var(--primary);
            color: var(--text-main);
            padding: 0.6rem 1.2rem;
            font-family: var(--font-condensed);
            font-size: 0.9rem;
            font-weight: 600;
            letter-spacing: 1px;
            text-transform: uppercase;
            cursor: pointer;
            transition: all 0.2s ease;
            clip-path: polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 8px 100%, 0 calc(100% - 8px));
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }

        .btn-secondary:hover:not(:disabled) {
            background-color: rgba(127, 90, 240, 0.15);
            color: #ffffff;
            border-color: var(--accent);
        }

        /* Terminal styling */
        .terminal-body {
            background-color: var(--terminal-bg);
            padding: 1.25rem;
            font-family: var(--font-mono);
            font-size: 0.8rem;
            line-height: 1.5;
            height: 330px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 4px;
            border: 1px solid rgba(127, 90, 240, 0.15);
            position: relative;
        }

        /* Scanline Overlay for retro-tactical screen */
        .terminal-body::before {
            content: " ";
            display: block;
            position: absolute;
            top: 0; left: 0; bottom: 0; right: 0;
            background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.06), rgba(0, 255, 0, 0.02), rgba(0, 0, 255, 0.06));
            z-index: 2;
            background-size: 100% 2px, 3px 100%;
            pointer-events: none;
        }

        .terminal-line {
            display: flex;
            gap: 8px;
            position: relative;
            z-index: 3;
        }

        .terminal-prompt {
            color: var(--accent);
            user-select: none;
        }

        .text-info { color: var(--text-main); }
        .text-success { color: var(--text-success); }
        .text-error { color: var(--text-error); }
        .text-iperf { color: var(--text-muted); opacity: 0.85; }

        /* Metrics Row */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1.5rem;
        }

        @media (max-width: 768px) {
            .metrics-grid {
                grid-template-columns: 1fr;
            }
        }

        .metric-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 1.25rem 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 4px;
            position: relative;
            clip-path: polygon(0 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%);
        }

        .metric-card::after {
            content: '';
            position: absolute;
            left: 0;
            bottom: 0;
            width: 4px;
            height: 70%;
            background-color: var(--primary);
        }

        .metric-card.accent-metric::after {
            background-color: var(--accent);
        }

        .metric-label {
            font-family: var(--font-condensed);
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: var(--text-muted);
        }

        .metric-value {
            font-size: 1.8rem;
            font-weight: 700;
            font-family: var(--font-mono);
            color: #ffffff;
            margin-top: 2px;
        }

        .metric-trend {
            font-size: 0.7rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        /* Results & Tabs */
        .tabs {
            display: flex;
            background-color: var(--bg-card-header);
            border-bottom: 1px solid var(--border-color);
        }

        .tab-link {
            background: none;
            border: none;
            color: var(--text-muted);
            padding: 1rem 1.5rem;
            font-family: var(--font-condensed);
            font-size: 0.95rem;
            font-weight: 600;
            letter-spacing: 1px;
            text-transform: uppercase;
            cursor: pointer;
            transition: all 0.2s ease;
            position: relative;
        }

        .tab-link:hover {
            color: #ffffff;
            background-color: rgba(255, 255, 255, 0.02);
        }

        .tab-link.active {
            color: #ffffff;
            background-color: var(--bg-card);
        }

        .tab-link.active::after {
            content: '';
            position: absolute;
            bottom: -1px;
            left: 0;
            width: 100%;
            height: 3px;
            background-color: var(--accent);
        }

        .tab-content {
            display: none;
            padding: 1.5rem;
        }

        .tab-content.active {
            display: block;
        }

        /* Table Design */
        .table-container {
            overflow-x: auto;
            border: 1px solid var(--border-color);
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
            text-align: left;
        }

        th {
            background-color: var(--bg-card-header);
            color: var(--text-muted);
            font-family: var(--font-condensed);
            font-weight: 600;
            padding: 0.75rem 1rem;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        td {
            padding: 0.85rem 1rem;
            border-bottom: 1px solid var(--border-color);
            color: var(--text-main);
        }

        tr:last-child td {
            border-bottom: none;
        }

        tr:hover td {
            background-color: rgba(127, 90, 240, 0.05);
        }

        .font-mono-data {
            font-family: var(--font-mono);
        }

        .action-footer {
            margin-top: 1.25rem;
            display: flex;
            justify-content: flex-end;
        }

        /* Charts styling */
        .charts-wrapper {
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }

        .charts-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }

        .charts-title {
            font-family: var(--font-title);
            font-size: 1.1rem;
            color: #ffffff;
            letter-spacing: 1px;
            text-transform: uppercase;
        }

        .chart-nav {
            display: flex;
            background-color: var(--bg-main);
            border: 1px solid var(--border-color);
        }

        .chart-nav-btn {
            background: none;
            border: none;
            color: var(--text-muted);
            padding: 0.4rem 1rem;
            font-family: var(--font-condensed);
            font-size: 0.8rem;
            font-weight: 600;
            letter-spacing: 1px;
            text-transform: uppercase;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .chart-nav-btn:hover {
            color: #ffffff;
        }

        .chart-nav-btn.active {
            background-color: var(--primary);
            color: #ffffff;
        }

        .chart-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1.5rem;
        }

        @media (max-width: 900px) {
            .chart-grid {
                grid-template-columns: 1fr;
            }
        }

        .chart-box {
            background-color: var(--bg-main);
            border: 1px solid var(--border-color);
            padding: 1.25rem;
            height: 280px;
            display: flex;
            flex-direction: column;
            position: relative;
        }

        /* Small Corner Crosshairs (+) for Arknights look */
        .chart-box::before {
            content: '+';
            position: absolute;
            top: 4px;
            left: 6px;
            font-family: var(--font-mono);
            font-size: 0.65rem;
            color: var(--text-muted);
            opacity: 0.5;
        }

        .chart-box h4 {
            font-family: var(--font-condensed);
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 1px;
            text-align: center;
            margin-bottom: 12px;
        }

        .chart-canvas-container {
            flex-grow: 1;
            position: relative;
            height: 0;
        }

        .no-data {
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-muted);
            font-style: italic;
            font-size: 0.9rem;
        }

        /* Spinner */
        .spinner {
            border: 2px solid rgba(255, 255, 255, 0.2);
            border-radius: 50%;
            border-top: 2px solid currentColor;
            width: 16px;
            height: 16px;
            animation: spin 0.8s linear infinite;
            display: inline-block;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header class="app-header">
            <div class="header-brand">
                <span class="brand-title">TCP OPTI<span class="accent-glow">FLOW</span></span>
                <span class="brand-sub">PRTS // CONGESTION_ANALYSIS_SYSTEM.v2.4</span>
            </div>
            <div class="status-panel">
                <div class="status-line">
                    <span class="status-label">SYS_MODE:</span>
                    <span class="status-value active">""" + sim_mode.upper() + """</span>
                </div>
                <div class="status-line">
                    <span class="status-label">SYS_STATUS:</span>
                    <span class="status-value">ONLINE</span>
                </div>
            </div>
        </header>

        <!-- Top Section -->
        <div class="layout-grid">
            <!-- Configuration Card -->
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">Experimental Setup</h2>
                    <span class="card-code">EX_01 // CTRL_PANEL</span>
                </div>
                <div class="card-body">
                    <div class="factor-group">
                        <div class="factor-row">
                            <div class="factor-header">
                                <span class="factor-label">Factor A: TCP Congestion Control</span>
                                <span class="factor-desc">Congestion avoidance algorithms under test</span>
                            </div>
                            <div class="factor-badges">
                                <span class="badge active">Reno</span>
                                <span class="badge active">Cubic</span>
                                <span class="badge active">BBR</span>
                            </div>
                        </div>
                        <div class="factor-row">
                            <div class="factor-header">
                                <span class="factor-label">Factor B: Link Bandwidth</span>
                                <span class="factor-desc">Bottleneck capacity constraints</span>
                            </div>
                            <div class="factor-badges">
                                <span class="badge active">100M</span>
                                <span class="badge active">500M</span>
                                <span class="badge active">1000M</span>
                            </div>
                        </div>
                        <div class="factor-row">
                            <div class="factor-header">
                                <span class="factor-label">Factor C: Link Delay</span>
                                <span class="factor-desc">Artificial round-trip latency</span>
                            </div>
                            <div class="factor-badges">
                                <span class="badge active">10ms</span>
                                <span class="badge active">50ms</span>
                                <span class="badge active">100ms</span>
                            </div>
                        </div>
                    </div>
                    <button id="btnRunSim" class="btn-primary" onclick="startSimulation()">
                        <span>Initiate Emulation Sequence</span>
                    </button>
                </div>
            </div>

            <!-- Terminal Card -->
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">Console Output</h2>
                    <span class="card-code">EX_02 // LIVE_STREAM_PRTS</span>
                </div>
                <div id="terminal" class="terminal-body">
                    <div class="terminal-line">
                        <span class="terminal-prompt">&gt;&gt;</span>
                        <span class="terminal-text text-info">PRTS initialized. Waiting for user execution command...</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Metrics Row (Hidden until data exists) -->
        <div class="metrics-grid" id="metricsGrid" style="display: none;">
            <div class="metric-card">
                <span class="metric-label">Mean Throughput</span>
                <div class="metric-value" id="valAvgThroughput">- Mbps</div>
                <span class="metric-trend">Across 9 trials</span>
            </div>
            <div class="metric-card">
                <span class="metric-label">Mean Stability (Var)</span>
                <div class="metric-value" id="valAvgVariance">-</div>
                <span class="metric-trend">Lower indicates higher stability</span>
            </div>
            <div class="metric-card accent-metric">
                <span class="metric-label">Mean Retransmission Rate</span>
                <div class="metric-value" id="valAvgRetrans" style="color: var(--accent);">- %</div>
                <span class="metric-trend">Protocol efficiency metric</span>
            </div>
        </div>

        <!-- Results Card (Hidden until data exists) -->
        <div class="card" id="resultsCard" style="display: none;">
            <div class="tabs">
                <button class="tab-link active" onclick="switchTab('tableTab', this)">Experimental Matrix</button>
                <button class="tab-link" onclick="switchTab('chartsTab', this)">Taguchi Main Effects Analysis</button>
            </div>

            <!-- Tab 1: Table -->
            <div id="tableTab" class="tab-content active">
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th style="text-align: center; width: 60px;">Run</th>
                                <th>TCP Algorithm</th>
                                <th style="text-align: right;">Bandwidth</th>
                                <th style="text-align: right;">Delay</th>
                                <th style="text-align: right;">Throughput</th>
                                <th style="text-align: right;">Stability (Var)</th>
                                <th style="text-align: right;">Retransmissions</th>
                            </tr>
                        </thead>
                        <tbody id="resultsTableBody">
                            <!-- Populated dynamically -->
                        </tbody>
                    </table>
                </div>
                <div class="action-footer">
                    <button class="btn-secondary" onclick="exportCSV()">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-top: 1px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                        <span style="margin-left: 4px;">Export CSV for Minitab / SPSS</span>
                    </button>
                </div>
            </div>

            <!-- Tab 2: Charts -->
            <div id="chartsTab" class="tab-content">
                <div class="charts-wrapper">
                    <div class="charts-header">
                        <span class="charts-title">Taguchi Factor Main Effects Plots</span>
                        <div class="chart-nav">
                            <button class="chart-nav-btn active" id="btnChartThroughput" onclick="changeChartResponse('throughput', this)">Throughput</button>
                            <button class="chart-nav-btn" id="btnChartRetrans" onclick="changeChartResponse('retrans_rate', this)">Retransmission</button>
                            <button class="chart-nav-btn" id="btnChartVariance" onclick="changeChartResponse('variance', this)">Variance</button>
                        </div>
                    </div>
                    
                    <div class="chart-grid">
                        <div class="chart-box">
                            <h4>Factor A: TCP Congestion Control</h4>
                            <div class="chart-canvas-container">
                                <canvas id="chartFactorA"></canvas>
                            </div>
                        </div>
                        <div class="chart-box">
                            <h4>Factor B: Bandwidth (Mbps)</h4>
                            <div class="chart-canvas-container">
                                <canvas id="chartFactorB"></canvas>
                            </div>
                        </div>
                        <div class="chart-box">
                            <h4>Factor C: Delay (ms)</h4>
                            <div class="chart-canvas-container">
                                <canvas id="chartFactorC"></canvas>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="card" id="noDataCard">
            <div class="no-data">
                No experimental data available. Execute the emulation sequence to generate results.
            </div>
        </div>
    </div>

    <script>
        let charts = {};
        let currentResponse = 'throughput';
        let latestResultsData = null;
        let latestMainEffectsData = null;

        function initCharts() {
            const chartConfigs = {
                chartFactorA: 'chartFactorA',
                chartFactorB: 'chartFactorB',
                chartFactorC: 'chartFactorC'
            };

            const chartOptions = {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: '#151121',
                        titleColor: '#e6e4eb',
                        bodyColor: '#e6e4eb',
                        borderColor: 'rgba(127, 90, 240, 0.4)',
                        borderWidth: 1,
                        padding: 8,
                        displayColors: false,
                        titleFont: { family: 'Share Tech', size: 12 },
                        bodyFont: { family: 'JetBrains Mono', size: 11 }
                    }
                },
                scales: {
                    y: {
                        grid: { color: 'rgba(127, 90, 240, 0.1)', drawBorder: false },
                        ticks: { color: '#746f88', font: { family: 'JetBrains Mono', size: 9 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#746f88', font: { family: 'Share Tech', size: 11 } }
                    }
                }
            };

            for (const [key, canvasId] of Object.entries(chartConfigs)) {
                if (charts[key]) {
                    charts[key].destroy();
                }
                const ctx = document.getElementById(canvasId).getContext('2d');
                charts[key] = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [{
                            data: [],
                            borderColor: '#7f5af0',
                            borderWidth: 2,
                            pointBackgroundColor: '#ff9f43',
                            pointBorderColor: '#07050b',
                            pointBorderWidth: 2,
                            pointRadius: 4,
                            pointHoverRadius: 6,
                            tension: 0,
                            fill: false
                        }]
                    },
                    options: chartOptions
                });
            }
        }

        function updateCharts(responseType) {
            if (!latestMainEffectsData) return;
            currentResponse = responseType;

            const configMapping = {
                throughput: { color: '#7f5af0', pointColor: '#ff9f43' },
                retrans_rate: { color: '#ff9f43', pointColor: '#7f5af0' },
                variance: { color: '#746f88', pointColor: '#7f5af0' }
            };

            const theme = configMapping[responseType];

            // Factor A (Algo)
            const algoData = latestMainEffectsData.algo;
            const algoVals = [
                algoData['reno'][responseType],
                algoData['cubic'][responseType],
                algoData['bbr'][responseType]
            ];

            // Factor B (BW)
            const bwData = latestMainEffectsData.bw;
            const bwVals = [
                bwData['100'][responseType],
                bwData['500'][responseType],
                bwData['1000'][responseType]
            ];

            // Factor C (Delay)
            const delayData = latestMainEffectsData.delay;
            const delayVals = [
                delayData['10'][responseType],
                delayData['50'][responseType],
                delayData['100'][responseType]
            ];

            // Update Chart A
            charts.chartFactorA.data.labels = ['Reno', 'Cubic', 'BBR'];
            charts.chartFactorA.data.datasets[0].data = algoVals;
            charts.chartFactorA.data.datasets[0].borderColor = theme.color;
            charts.chartFactorA.data.datasets[0].pointBackgroundColor = theme.pointColor;
            charts.chartFactorA.update();

            // Update Chart B
            charts.chartFactorB.data.labels = ['100M', '500M', '1G'];
            charts.chartFactorB.data.datasets[0].data = bwVals;
            charts.chartFactorB.data.datasets[0].borderColor = theme.color;
            charts.chartFactorB.data.datasets[0].pointBackgroundColor = theme.pointColor;
            charts.chartFactorB.update();

            // Update Chart C
            charts.chartFactorC.data.labels = ['10ms', '50ms', '100ms'];
            charts.chartFactorC.data.datasets[0].data = delayVals;
            charts.chartFactorC.data.datasets[0].borderColor = theme.color;
            charts.chartFactorC.data.datasets[0].pointBackgroundColor = theme.pointColor;
            charts.chartFactorC.update();
        }

        function changeChartResponse(responseType, element) {
            document.querySelectorAll('.chart-nav-btn').forEach(btn => btn.classList.remove('active'));
            element.classList.add('active');
            updateCharts(responseType);
        }

        function switchTab(tabId, element) {
            document.querySelectorAll('.tabs .tab-link').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            
            element.classList.add('active');
            document.getElementById(tabId).classList.add('active');

            if (tabId === 'chartsTab') {
                setTimeout(() => {
                    Object.values(charts).forEach(c => c.resize());
                }, 50);
            }
        }

        function appendTerminalLine(time, text, type) {
            const terminal = document.getElementById('terminal');
            const line = document.createElement('div');
            line.className = 'terminal-line';
            
            const promptSpan = document.createElement('span');
            promptSpan.className = 'terminal-prompt';
            promptSpan.textContent = '>>';
            
            const textSpan = document.createElement('span');
            textSpan.className = `terminal-text text-${type}`;
            textSpan.textContent = text;
            
            line.appendChild(promptSpan);
            line.appendChild(textSpan);
            terminal.appendChild(line);
            
            terminal.scrollTop = terminal.scrollHeight;
        }

        function startSimulation() {
            const btn = document.getElementById('btnRunSim');
            btn.disabled = true;
            btn.classList.add('running');
            btn.innerHTML = '<span class="spinner"></span> <span>ANALYZING...</span>';

            document.getElementById('terminal').innerHTML = '';
            appendTerminalLine(new Date().toLocaleTimeString(), 'Initializing tactical diagnostic handshake...', 'info');

            fetch('/api/run', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'started') {
                        setupLogStream();
                    } else {
                        appendTerminalLine(new Date().toLocaleTimeString(), 'Execution aborted: ' + data.message, 'error');
                        resetRunButton();
                    }
                })
                .catch(err => {
                    appendTerminalLine(new Date().toLocaleTimeString(), 'Server connection failed: ' + err, 'error');
                    resetRunButton();
                });
        }

        function resetRunButton() {
            const btn = document.getElementById('btnRunSim');
            btn.disabled = false;
            btn.classList.remove('running');
            btn.innerHTML = '<span>Run Analyzer Sequence</span>';
        }

        function setupLogStream() {
            const eventSource = new EventSource('/api/stream');
            
            eventSource.onmessage = function(event) {
                const data = JSON.parse(event.data);
                
                if (data.type === 'status' && data.status === 'done') {
                    eventSource.close();
                    appendTerminalLine(new Date().toLocaleTimeString(), 'Sequence terminated. Pulling data matrices...', 'success');
                    fetchResults();
                    resetRunButton();
                } else {
                    appendTerminalLine(data.time, data.text, data.type);
                }
            };

            eventSource.onerror = function(err) {
                console.error('SSE connection lost:', err);
                eventSource.close();
                resetRunButton();
            };
        }

        function fetchResults() {
            fetch('/api/results')
                .then(res => res.json())
                .then(data => {
                    if (data.results && data.results.length > 0) {
                        latestResultsData = data.results;
                        latestMainEffectsData = data.main_effects;
                        populateUI(data.results, data.main_effects);
                    }
                })
                .catch(err => {
                    console.error('Failed to retrieve results:', err);
                });
        }

        function populateUI(results, mainEffects) {
            document.getElementById('metricsGrid').style.display = 'grid';
            document.getElementById('resultsCard').style.display = 'block';
            document.getElementById('noDataCard').style.display = 'none';

            let totalThr = 0, totalVar = 0, totalRetr = 0;
            results.forEach(r => {
                totalThr += r.throughput;
                totalVar += r.variance;
                totalRetr += r.retrans_rate;
            });
            const avgThr = totalThr / results.length;
            const avgVar = totalVar / results.length;
            const avgRetr = totalRetr / results.length;

            document.getElementById('valAvgThroughput').innerText = `${avgThr.toFixed(2)} Mbps`;
            document.getElementById('valAvgVariance').innerText = avgVar.toFixed(4);
            document.getElementById('valAvgRetrans').innerText = `${avgRetr.toFixed(4)} %`;

            const tbody = document.getElementById('resultsTableBody');
            tbody.innerHTML = '';
            results.forEach(r => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td style="text-align: center;" class="font-mono-data">${r.run}</td>
                    <td style="font-weight: 500; text-transform: uppercase;">${r.algo}</td>
                    <td style="text-align: right;" class="font-mono-data">${r.bw} Mbps</td>
                    <td style="text-align: right;" class="font-mono-data">${r.delay} ms</td>
                    <td style="text-align: right; font-weight: 600;" class="font-mono-data">${r.throughput.toFixed(2)}</td>
                    <td style="text-align: right; color: var(--text-muted);" class="font-mono-data">${r.variance.toFixed(4)}</td>
                    <td style="text-align: right; font-weight: 600; color: var(--accent);" class="font-mono-data">${r.retrans_rate.toFixed(4)}%</td>
                `;
                tbody.appendChild(tr);
            });

            updateCharts(currentResponse);
        }

        function exportCSV() {
            window.location.href = '/api/export';
        }

        window.onload = function() {
            initCharts();
            fetchResults();
        };
    </script>
</body>
</html>
"""

@app.route("/api/run", methods=["POST"])
def run_simulation():
    """Trigger the simulation sequence in a background thread."""
    global is_running
    
    with state_lock:
        if is_running:
            return jsonify({"status": "error", "message": "Simulation is already running"}), 400
            
    # Spawn background thread
    thread = threading.Thread(target=run_simulation_sequence)
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "started", "message": "Simulation initiated"})

@app.route("/api/stream")
def stream_logs():
    """Server-Sent Events endpoint to stream terminal logs to the browser."""
    def generate():
        idx = 0
        while True:
            # Check for new logs
            with log_lock:
                if idx < len(log_queue):
                    for i in range(idx, len(log_queue)):
                        yield f"data: {json.dumps(log_queue[i])}\n\n"
                    idx = len(log_queue)
                    
            # Check if running has finished
            with state_lock:
                currently_running = is_running
                
            if not currently_running and idx >= len(log_queue):
                # Send terminal connection termination event
                yield f"data: {json.dumps({'type': 'status', 'status': 'done'})}\n\n"
                break
                
            time.sleep(0.1)
            
    return Response(generate(), mimetype='text/event-stream')

@app.route("/api/results")
def get_results():
    """Returns the latest experimental results and calculated main effects."""
    with state_lock:
        return jsonify({
            "results": latest_results,
            "main_effects": main_effects,
            "mode": sim_mode
        })

@app.route("/api/export")
def export_results():
    """Downloads the generated CSV file."""
    if not os.path.exists(CSV_FILENAME):
        return jsonify({"status": "error", "message": "No results CSV found. Run the simulation first."}), 404
        
    try:
        return send_file(
            CSV_FILENAME,
            mimetype="text/csv",
            as_attachment=True,
            download_name=CSV_FILENAME
        )
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to download file: {str(e)}"}), 500

# ==========================================
# 6. Main Entry Point
# ==========================================
if __name__ == "__main__":
    print("====================================================")
    print("   TCP OptiFlow Emulation & Analysis Software       ")
    print("====================================================")
    print(f"Detected Mode: {sim_mode}")
    if not has_mininet:
        print(f"Reason: {mode_reason}")
        print("Note: Running on Windows or non-root. Emulation will use physical Mock Mode.")
    else:
        print("Emulation will execute physical Mininet trials.")
    print("Server running at: http://localhost:5000")
    print("Press Ctrl+C to terminate.")
    print("====================================================")
    
    # Check if a previous results CSV exists, and load it to pre-populate the UI
    if os.path.exists(CSV_FILENAME):
        try:
            with open(CSV_FILENAME, mode='r') as f:
                reader = csv.DictReader(f)
                latest_results = []
                for row in reader:
                    latest_results.append({
                        "run": int(row["Run"]),
                        "algo": row["TCP_Algorithm"],
                        "bw": int(row["Bandwidth_Mbps"]),
                        "delay": int(row["Delay_ms"]),
                        "throughput": float(row["Throughput_Mbps"]),
                        "variance": float(row["Throughput_Variance"]),
                        "retrans_rate": float(row["Retransmission_Rate_Pct"]),
                        "retransmits": int(row["Retransmits"])
                    })
            main_effects = compute_taguchi_analysis(latest_results)
            print(f"[+] Pre-loaded {len(latest_results)} historical runs from {CSV_FILENAME}")
        except Exception as e:
            print(f"[-] Could not pre-load historical data: {str(e)}")
            latest_results = []
            main_effects = {}

    # Disable Flask logging to prevent cluttering the terminal output
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\nServer shutting down. Goodbye!")
        sys.exit(0)
