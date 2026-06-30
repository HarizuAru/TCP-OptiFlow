#!/usr/bin/env python3
"""
tcp_regime_sim.py - TCP OptiFlow Emulation & Analysis Software
Styled with a Wuthering Waves 'Mornye' Cosmic Researcher Theme.

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
    # Embedded HTML with Mornye Theme (Cosmic purple + Fusion orange)
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TCP OptiFlow - Mornye Research Lab</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-color: #0b0914;
            --bg-gradient: linear-gradient(135deg, #0b0914 0%, #151128 100%);
            --panel-bg: rgba(26, 21, 48, 0.6);
            --panel-border: rgba(108, 92, 231, 0.25);
            --panel-border-glow: rgba(108, 92, 231, 0.5);
            
            /* Mornye Color Palette */
            --primary: #7f5af0; /* Noble Lavender/Purple */
            --primary-glow: rgba(127, 90, 240, 0.4);
            --secondary: #a89fec; /* Soft Lavender */
            
            /* Fusion Element Accent (Gold/Fire Orange) */
            --fusion: #ff9f43; 
            --fusion-glow: rgba(255, 159, 67, 0.4);
            --fusion-dark: #e67e22;
            
            /* UI Colors */
            --text-main: #f3f0ff;
            --text-muted: #9f9bbd;
            --text-success: #55efc4;
            --text-error: #ff7675;
            --terminal-bg: #06040a;
            
            --transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background: var(--bg-gradient);
            color: var(--text-main);
            min-height: 100vh;
            overflow-x: hidden;
            background-attachment: fixed;
        }

        /* Ambient Cosmic Glows */
        .ambient-glow-1 {
            position: fixed;
            width: 500px;
            height: 500px;
            background: radial-gradient(circle, rgba(127, 90, 240, 0.12) 0%, rgba(0,0,0,0) 70%);
            top: -100px;
            right: -100px;
            z-index: -1;
            pointer-events: none;
        }
        
        .ambient-glow-2 {
            position: fixed;
            width: 600px;
            height: 600px;
            background: radial-gradient(circle, rgba(255, 159, 67, 0.05) 0%, rgba(0,0,0,0) 70%);
            bottom: -200px;
            left: -200px;
            z-index: -1;
            pointer-events: none;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        /* Glassmorphic Header */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.5rem 2rem;
            background: var(--panel-bg);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid var(--panel-border);
            border-radius: 20px;
            margin-bottom: 2rem;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
        }

        .logo-container h1 {
            font-size: 1.8rem;
            font-weight: 700;
            letter-spacing: 2px;
            background: linear-gradient(to right, var(--text-main), var(--secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .logo-container h1 span.accent-text {
            color: var(--fusion);
            -webkit-text-fill-color: var(--fusion);
            text-shadow: 0 0 10px var(--fusion-glow);
        }

        .logo-container p {
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-top: 2px;
            letter-spacing: 1px;
            text-transform: uppercase;
        }

        .system-badge {
            background: rgba(127, 90, 240, 0.15);
            border: 1px solid var(--panel-border-glow);
            padding: 0.5rem 1rem;
            border-radius: 30px;
            font-size: 0.85rem;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 8px;
            letter-spacing: 0.5px;
        }

        .system-badge .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--fusion);
            box-shadow: 0 0 8px var(--fusion);
        }

        /* Dashboard Layout Grid */
        .grid-top {
            display: grid;
            grid-template-columns: 1fr 1.5fr;
            gap: 2rem;
            margin-bottom: 2rem;
        }

        @media (max-width: 1024px) {
            .grid-top {
                grid-template-columns: 1fr;
            }
        }

        /* Glass Cards */
        .card {
            background: var(--panel-bg);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid var(--panel-border);
            border-radius: 20px;
            padding: 2rem;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
            display: flex;
            flex-direction: column;
            position: relative;
            overflow: hidden;
        }

        .card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: var(--primary);
            opacity: 0.7;
        }

        .card.accent-card::before {
            background: var(--fusion);
        }

        .card-title {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            padding-bottom: 0.75rem;
            letter-spacing: 0.5px;
        }

        /* Configuration Panel Details */
        .factor-list {
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
            margin-bottom: 1.5rem;
            flex-grow: 1;
        }

        .factor-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(255, 255, 255, 0.02);
            padding: 0.75rem 1rem;
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.03);
        }

        .factor-name {
            font-weight: 500;
            font-size: 0.95rem;
        }

        .factor-levels {
            display: flex;
            gap: 6px;
        }

        .level-badge {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255,255,255,0.1);
            padding: 0.25rem 0.6rem;
            border-radius: 6px;
            font-size: 0.8rem;
            font-family: 'Fira Code', monospace;
            color: var(--secondary);
        }

        .btn-run {
            background: linear-gradient(135deg, var(--primary) 0%, #6c5ce7 100%);
            color: white;
            border: none;
            padding: 1rem 2rem;
            font-size: 1.1rem;
            font-weight: 600;
            border-radius: 12px;
            cursor: pointer;
            transition: var(--transition);
            box-shadow: 0 4px 15px var(--primary-glow);
            letter-spacing: 1px;
            text-transform: uppercase;
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
        }

        .btn-run:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(127, 90, 240, 0.6);
            background: linear-gradient(135deg, #8a65ff 0%, #7d6eff 100%);
        }

        .btn-run:active:not(:disabled) {
            transform: translateY(1px);
        }

        .btn-run:disabled {
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-muted);
            border: 1px solid rgba(255,255,255,0.05);
            cursor: not-allowed;
            box-shadow: none;
        }

        .btn-run.running {
            background: linear-gradient(135deg, var(--fusion) 0%, var(--fusion-dark) 100%);
            box-shadow: 0 4px 15px var(--fusion-glow);
            animation: pulse-glow 2s infinite;
        }

        @keyframes pulse-glow {
            0% { box-shadow: 0 0 5px var(--fusion-glow); }
            50% { box-shadow: 0 0 20px var(--fusion-glow); }
            100% { box-shadow: 0 0 5px var(--fusion-glow); }
        }

        /* Terminal Display */
        .terminal-container {
            background: var(--terminal-bg);
            border: 1px solid rgba(127, 90, 240, 0.15);
            border-radius: 16px;
            padding: 1.25rem;
            font-family: 'Fira Code', monospace;
            font-size: 0.85rem;
            line-height: 1.5;
            height: 350px;
            overflow-y: auto;
            box-shadow: inset 0 4px 20px rgba(0, 0, 0, 0.8);
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .terminal-line {
            display: flex;
            gap: 10px;
        }

        .terminal-time {
            color: var(--text-muted);
            opacity: 0.5;
            flex-shrink: 0;
            user-select: none;
        }

        .terminal-text {
            word-break: break-all;
            white-space: pre-wrap;
        }

        .text-info { color: var(--terminal-text); }
        .text-success { color: var(--text-success); }
        .text-error { color: var(--text-error); }
        .text-iperf { color: #81ecec; opacity: 0.9; }

        /* Summary Metrics Grid */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        @media (max-width: 768px) {
            .metrics-grid {
                grid-template-columns: 1fr;
            }
        }

        .metric-card {
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            border-radius: 16px;
            padding: 1.5rem;
            display: flex;
            align-items: center;
            gap: 1.25rem;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
            position: relative;
        }

        .metric-icon {
            width: 48px;
            height: 48px;
            border-radius: 12px;
            background: rgba(127, 90, 240, 0.15);
            border: 1px solid var(--panel-border-glow);
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--secondary);
            font-size: 1.5rem;
        }

        .metric-card.accent-metric .metric-icon {
            background: rgba(255, 159, 67, 0.15);
            border: 1px solid var(--fusion-glow);
            color: var(--fusion);
        }

        .metric-info h3 {
            font-size: 0.85rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .metric-value {
            font-size: 1.6rem;
            font-weight: 700;
            margin-top: 4px;
        }

        /* Results & Tabs Section */
        .analysis-section {
            margin-top: 2rem;
        }

        .tabs-header {
            display: flex;
            gap: 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 1rem;
            margin-bottom: 1.5rem;
        }

        .tab-btn {
            background: none;
            border: none;
            color: var(--text-muted);
            font-family: 'Outfit', sans-serif;
            font-size: 1rem;
            font-weight: 500;
            padding: 0.5rem 1.25rem;
            cursor: pointer;
            border-radius: 8px;
            transition: var(--transition);
        }

        .tab-btn:hover {
            color: var(--text-main);
            background: rgba(255, 255, 255, 0.02);
        }

        .tab-btn.active {
            color: var(--text-main);
            background: rgba(127, 90, 240, 0.15);
            border: 1px solid var(--panel-border-glow);
        }

        .tab-content {
            display: none;
        }

        .tab-content.active {
            display: block;
        }

        /* Table Design */
        .table-wrapper {
            overflow-x: auto;
            border-radius: 12px;
            border: 1px solid var(--panel-border);
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.95rem;
        }

        th {
            background: rgba(127, 90, 240, 0.1);
            padding: 1rem;
            font-weight: 600;
            color: var(--secondary);
            border-bottom: 1px solid var(--panel-border);
            letter-spacing: 0.5px;
        }

        td {
            padding: 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
            background: rgba(26, 21, 48, 0.3);
        }

        tr:last-child td {
            border-bottom: none;
        }

        tr:hover td {
            background: rgba(127, 90, 240, 0.05);
        }

        .highlight-cell {
            font-family: 'Fira Code', monospace;
            font-weight: 500;
        }

        /* Charts Layout */
        .charts-container {
            display: flex;
            flex-direction: column;
            gap: 2rem;
        }

        .chart-selector {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            margin-bottom: 1rem;
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

        .chart-panel {
            background: rgba(26, 21, 48, 0.4);
            border: 1px solid var(--panel-border);
            border-radius: 16px;
            padding: 1.25rem;
            height: 300px;
            position: relative;
        }

        .chart-panel h4 {
            font-size: 0.9rem;
            text-transform: uppercase;
            color: var(--text-muted);
            text-align: center;
            margin-bottom: 10px;
            letter-spacing: 0.5px;
        }

        .btn-export {
            align-self: flex-start;
            background: transparent;
            border: 1px solid var(--fusion);
            color: var(--fusion);
            padding: 0.75rem 1.5rem;
            font-weight: 600;
            border-radius: 10px;
            cursor: pointer;
            transition: var(--transition);
            margin-top: 1.5rem;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .btn-export:hover {
            background: var(--fusion);
            color: var(--bg-color);
            box-shadow: 0 0 15px var(--fusion-glow);
        }

        /* Loading Spinner */
        .spinner {
            border: 2px solid rgba(255, 255, 255, 0.1);
            border-radius: 50%;
            border-top: 2px solid var(--text-main);
            width: 20px;
            height: 20px;
            animation: spin 0.8s linear infinite;
            display: inline-block;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .no-data-msg {
            text-align: center;
            padding: 4rem;
            color: var(--text-muted);
            font-style: italic;
        }
    </style>
</head>
<body>
    <div class="ambient-glow-1"></div>
    <div class="ambient-glow-2"></div>

    <div class="container">
        <!-- Header -->
        <header>
            <div class="logo-container">
                <h1>TCP OPTI<span class="accent-text">FLOW</span></h1>
                <p>Advanced Congestion Regime Emulation Software</p>
            </div>
            <div class="system-badge">
                <span class="dot"></span>
                <span>SYSTEM: """ + sim_mode + """</span>
            </div>
        </header>

        <!-- Top Section: Config and Terminal -->
        <div class="grid-top">
            <!-- Left: Configuration -->
            <div class="card">
                <h2 class="card-title">
                    <span>Experimental Design</span>
                    <span style="font-size: 0.8rem; color: var(--fusion); font-family: 'Fira Code';">Taguchi L9 (3³ Factorial)</span>
                </h2>
                <ul class="factor-list">
                    <li class="factor-item">
                        <div class="factor-name">Factor A: TCP Congestion Control</div>
                        <div class="factor-levels">
                            <span class="level-badge">Reno</span>
                            <span class="level-badge">Cubic</span>
                            <span class="level-badge">BBR</span>
                        </div>
                    </li>
                    <li class="factor-item">
                        <div class="factor-name">Factor B: Link Bandwidth</div>
                        <div class="factor-levels">
                            <span class="level-badge">100M</span>
                            <span class="level-badge">500M</span>
                            <span class="level-badge">1G</span>
                        </div>
                    </li>
                    <li class="factor-item">
                        <div class="factor-name">Factor C: Artificial Link Delay</div>
                        <div class="factor-levels">
                            <span class="level-badge">10ms</span>
                            <span class="level-badge">50ms</span>
                            <span class="level-badge">100ms</span>
                        </div>
                    </li>
                </ul>
                <button id="btnRunSim" class="btn-run" onclick="startSimulation()">
                    <span>Initiate Emulation</span>
                </button>
            </div>

            <!-- Right: Real-time Terminal -->
            <div class="card accent-card">
                <h2 class="card-title">
                    <span>Research Terminal Logs</span>
                    <span style="font-size: 0.8rem; color: var(--text-muted); font-family: 'Fira Code';">SSE Connection</span>
                </h2>
                <div id="terminal" class="terminal-container">
                    <div class="terminal-line">
                        <span class="terminal-time">[System]</span>
                        <span class="terminal-text text-info">Ready to initiate. Click 'Initiate Emulation' to start testing.</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Middle Section: Key Metrics -->
        <div class="metrics-grid" id="metricsGrid" style="display: none;">
            <div class="metric-card">
                <div class="metric-icon">⚡</div>
                <div class="metric-info">
                    <h3>Average Throughput</h3>
                    <div class="metric-value" id="valAvgThroughput">- Mbps</div>
                </div>
            </div>
            <div class="metric-card">
                <div class="metric-icon">⚖️</div>
                <div class="metric-info">
                    <h3>Mean Stability Index (Variance)</h3>
                    <div class="metric-value" id="valAvgVariance">-</div>
                </div>
            </div>
            <div class="metric-card accent-metric">
                <div class="metric-icon" style="color: var(--fusion);">⚠️</div>
                <div class="metric-info">
                    <h3>Average Retransmission Rate</h3>
                    <div class="metric-value" id="valAvgRetrans" style="color: var(--fusion);">- %</div>
                </div>
            </div>
        </div>

        <!-- Bottom Section: Results Tabs -->
        <div class="card" id="resultsCard" style="display: none;">
            <div class="tabs-header">
                <button class="tab-btn active" onclick="switchTab('tableTab', this)">Experimental Matrix</button>
                <button class="tab-btn" onclick="switchTab('chartsTab', this)">Taguchi Main Effects Analysis</button>
            </div>

            <!-- Tab 1: Table -->
            <div id="tableTab" class="tab-content active">
                <div class="table-wrapper">
                    <table>
                        <thead>
                            <tr>
                                <th>Run</th>
                                <th>TCP Algorithm (A)</th>
                                <th>Bandwidth (B)</th>
                                <th>Delay (C)</th>
                                <th>Throughput (Mbps)</th>
                                <th>Stability Variance</th>
                                <th>Retransmissions (%)</th>
                            </tr>
                        </thead>
                        <tbody id="resultsTableBody">
                            <!-- Populated dynamically -->
                        </tbody>
                    </table>
                </div>
                <button class="btn-export" onclick="exportCSV()">
                    <span>Download CSV for Minitab/SPSS</span>
                </button>
            </div>

            <!-- Tab 2: Charts -->
            <div id="chartsTab" class="tab-content">
                <div class="charts-container">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                        <span style="font-size: 0.95rem; color: var(--text-muted);">Main Effects Plot (Data Means)</span>
                        <div class="chart-selector">
                            <button class="tab-btn active" id="btnChartThroughput" onclick="changeChartResponse('throughput', this)">Throughput</button>
                            <button class="tab-btn" id="btnChartRetrans" onclick="changeChartResponse('retrans_rate', this)">Retransmission</button>
                            <button class="tab-btn" id="btnChartVariance" onclick="changeChartResponse('variance', this)">Variance</button>
                        </div>
                    </div>
                    
                    <div class="chart-grid">
                        <div class="chart-panel">
                            <h4>Factor A: TCP Congestion Control</h4>
                            <canvas id="chartFactorA"></canvas>
                        </div>
                        <div class="chart-panel">
                            <h4>Factor B: Bandwidth (Mbps)</h4>
                            <canvas id="chartFactorB"></canvas>
                        </div>
                        <div class="chart-panel">
                            <h4>Factor C: Delay (ms)</h4>
                            <canvas id="chartFactorC"></canvas>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="card" id="noDataCard">
            <div class="no-data-msg">
                No experimental data available. Please trigger the emulation script to populate results.
            </div>
        </div>
    </div>

    <script>
        let charts = {};
        let currentResponse = 'throughput';
        let latestResultsData = null;
        let latestMainEffectsData = null;

        // Initialize empty charts
        function initCharts() {
            const chartConfigs = {
                chartFactorA: { el: 'chartFactorA', label: 'TCP Algo' },
                chartFactorB: { el: 'chartFactorB', label: 'Bandwidth' },
                chartFactorC: { el: 'chartFactorC', label: 'Delay' }
            };

            for (const [key, config] of Object.entries(chartConfigs)) {
                if (charts[key]) {
                    charts[key].destroy();
                }
                const ctx = document.getElementById(config.el).getContext('2d');
                charts[key] = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: [],
                        datasets: [{
                            label: '',
                            data: [],
                            borderColor: '#7f5af0',
                            backgroundColor: 'rgba(127, 90, 240, 0.2)',
                            borderWidth: 3,
                            pointBackgroundColor: '#ff9f43',
                            pointBorderColor: '#fff',
                            pointRadius: 6,
                            tension: 0.1
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false }
                        },
                        scales: {
                            y: {
                                grid: { color: 'rgba(255, 255, 255, 0.05)' },
                                ticks: { color: '#9f9bbd' }
                            },
                            x: {
                                grid: { display: false },
                                ticks: { color: '#9f9bbd' }
                            }
                        }
                    }
                });
            }
        }

        function updateCharts(responseType) {
            if (!latestMainEffectsData) return;
            currentResponse = responseType;

            const mapping = {
                throughput: { label: 'Throughput (Mbps)', color: '#7f5af0' },
                retrans_rate: { label: 'Retransmission Rate (%)', color: '#ff9f43' },
                variance: { label: 'Variance', color: '#a89fec' }
            };

            const selected = mapping[responseType];

            // Factor A (Algo)
            const algoData = latestMainEffectsData.algo;
            const algoLabels = ['Reno', 'Cubic', 'BBR'];
            const algoVals = [
                algoData['reno'][responseType],
                algoData['cubic'][responseType],
                algoData['bbr'][responseType]
            ];

            // Factor B (BW)
            const bwData = latestMainEffectsData.bw;
            const bwLabels = ['100', '500', '1000'];
            const bwVals = [
                bwData['100'][responseType],
                bwData['500'][responseType],
                bwData['1000'][responseType]
            ];

            // Factor C (Delay)
            const delayData = latestMainEffectsData.delay;
            const delayLabels = ['10', '50', '100'];
            const delayVals = [
                delayData['10'][responseType],
                delayData['50'][responseType],
                delayData['100'][responseType]
            ];

            // Update Chart A
            charts.chartFactorA.data.labels = algoLabels;
            charts.chartFactorA.data.datasets[0].data = algoVals;
            charts.chartFactorA.data.datasets[0].borderColor = selected.color;
            charts.chartFactorA.data.datasets[0].label = selected.label;
            charts.chartFactorA.update();

            // Update Chart B
            charts.chartFactorB.data.labels = bwLabels;
            charts.chartFactorB.data.datasets[0].data = bwVals;
            charts.chartFactorB.data.datasets[0].borderColor = selected.color;
            charts.chartFactorB.data.datasets[0].label = selected.label;
            charts.chartFactorB.update();

            // Update Chart C
            charts.chartFactorC.data.labels = delayLabels;
            charts.chartFactorC.data.datasets[0].data = delayVals;
            charts.chartFactorC.data.datasets[0].borderColor = selected.color;
            charts.chartFactorC.data.datasets[0].label = selected.label;
            charts.chartFactorC.update();
        }

        function changeChartResponse(responseType, element) {
            document.querySelectorAll('.chart-selector .tab-btn').forEach(btn => btn.classList.remove('active'));
            element.classList.add('active');
            updateCharts(responseType);
        }

        function switchTab(tabId, element) {
            document.querySelectorAll('.tabs-header .tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            
            element.classList.add('active');
            document.getElementById(tabId).classList.add('active');

            // Resize charts on display to fix rendering bugs in hidden canvases
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
            
            const timeSpan = document.createElement('span');
            timeSpan.className = 'terminal-time';
            timeSpan.textContent = `[${time}]`;
            
            const textSpan = document.createElement('span');
            textSpan.className = `terminal-text text-${type}`;
            textSpan.textContent = text;
            
            line.appendChild(timeSpan);
            line.appendChild(textSpan);
            terminal.appendChild(line);
            
            // Auto scroll to bottom
            terminal.scrollTop = terminal.scrollHeight;
        }

        function startSimulation() {
            const btn = document.getElementById('btnRunSim');
            btn.disabled = true;
            btn.classList.add('running');
            btn.innerHTML = '<span class="spinner"></span> <span>Running Simulation...</span>';

            // Clear terminal
            document.getElementById('terminal').innerHTML = '';
            appendTerminalLine(new Date().toLocaleTimeString(), 'Contacting server...', 'info');

            fetch('/api/run', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'started') {
                        setupLogStream();
                    } else {
                        appendTerminalLine(new Date().toLocaleTimeString(), 'Error: ' + data.message, 'error');
                        resetRunButton();
                    }
                })
                .catch(err => {
                    appendTerminalLine(new Date().toLocaleTimeString(), 'Connection failure: ' + err, 'error');
                    resetRunButton();
                });
        }

        function resetRunButton() {
            const btn = document.getElementById('btnRunSim');
            btn.disabled = false;
            btn.classList.remove('running');
            btn.innerHTML = '<span>Initiate Emulation</span>';
        }

        function setupLogStream() {
            const eventSource = new EventSource('/api/stream');
            
            eventSource.onmessage = function(event) {
                const data = JSON.parse(event.data);
                
                if (data.type === 'status' && data.status === 'done') {
                    eventSource.close();
                    appendTerminalLine(new Date().toLocaleTimeString(), 'Event stream closed. Fetching results...', 'info');
                    fetchResults();
                    resetRunButton();
                } else {
                    appendTerminalLine(data.time, data.text, data.type);
                }
            };

            eventSource.onerror = function(err) {
                console.error('SSE Error:', err);
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
                    console.error('Error fetching results:', err);
                });
        }

        function populateUI(results, mainEffects) {
            // Unhide metrics and results
            document.getElementById('metricsGrid').style.display = 'grid';
            document.getElementById('resultsCard').style.display = 'block';
            document.getElementById('noDataCard').style.display = 'none';

            // Calculate overall averages
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

            // Populate table
            const tbody = document.getElementById('resultsTableBody');
            tbody.innerHTML = '';
            results.forEach(r => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="highlight-cell">${r.run}</td>
                    <td class="highlight-cell" style="text-transform: uppercase;">${r.algo}</td>
                    <td>${r.bw} Mbps</td>
                    <td>${r.delay} ms</td>
                    <td class="highlight-cell" style="color: var(--secondary);">${r.throughput.toFixed(2)}</td>
                    <td>${r.variance.toFixed(4)}</td>
                    <td class="highlight-cell" style="color: var(--fusion);">${r.retrans_rate.toFixed(4)}</td>
                `;
                tbody.appendChild(tr);
            });

            // Update Charts
            updateCharts(currentResponse);
        }

        function exportCSV() {
            window.location.href = '/api/export';
        }

        // Initialize on load
        window.onload = function() {
            initCharts();
            // Check if there are existing results from a previous run
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
    print("   TCP OptiFlow Emulation Software - Mornye Theme   ")
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
