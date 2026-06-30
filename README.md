# TCP OptiFlow: Congestion Regime Emulation Software

Welcome to **TCP OptiFlow**, an advanced network emulation and statistical analysis prototype designed to investigate TCP congestion control states in high-speed, high-latency networks. 

This software is designed as an advanced network emulation and statistical analysis prototype. It features a responsive, clean dark-mode web dashboard, live terminal logs streamed via Server-Sent Events (SSE), and interactive **Taguchi Main Effects Plots** powered by Chart.js.

---

## 1. Theoretical Background

High-Speed, High-Latency networks (often referred to as **LFNs** or Long Fat Networks) present a unique challenge to TCP congestion control. The capacity of a network path is defined by its **Bandwidth-Delay Product (BDP)**:

$$\text{BDP (bits)} = \text{Bandwidth (bps)} \times \text{Round-Trip Time (sec)}$$

To fully utilize the network, a TCP sender must maintain a congestion window (cwnd) equal to or greater than the BDP. This prototype compares three distinct generations of TCP congestion control:

### A. TCP Reno (Loss-Based, AIMD)
- **Mechanism**: Employs Additive Increase, Multiplicative Decrease. It increases its congestion window by 1 MSS per RTT, and cuts it in half when a packet loss is detected.
- **LFN Behavior**: Extremely poor performance. In high BDP networks, once a loss occurs, Reno takes hundreds of RTTs to rebuild its window to fill the pipe. It suffers from **high throughput variance** (sawtooth oscillations) and **high retransmission rates** under congestion.

### B. TCP Cubic (Loss-Based, Cubic Window Growth)
- **Mechanism**: The default congestion control in Linux. The window growth is governed by a cubic function of time elapsed since the last congestion event, making window growth independent of RTT.
- **LFN Behavior**: Significantly better than Reno. It scales much faster to fill large BDP pipes, but because it is still loss-based, it still suffers from throughput drops and high retransmission rates when packet buffers fill and overflow.

### C. TCP BBR (Model-Based)
- **Mechanism**: Developed by Google. BBR (Bottleneck Bandwidth and RTT) does not use packet loss as a primary congestion signal. Instead, it builds an explicit model of the network path by pacing packets and measuring the maximum bandwidth and minimum RTT.
- **LFN Behavior**: Outstanding performance. It maintains near-line-rate throughput even under high latency and packet loss. It prevents queue buildup at the bottleneck switch, leading to **extremely low throughput variance** (high stability) and **minimal retransmission rates**.

---

## 2. Taguchi L9 Orthogonal Array Design

Rather than running a full factorial experiment (which would require $3 \text{ factors} \times 3 \text{ levels} = 27$ runs), this software utilizes a **Taguchi L9 ($3^3$) Orthogonal Array**. This design reduces the number of experimental runs to just **9 runs** while still allowing us to mathematically separate and analyze the main effects of each factor on the network responses.

### Experimental Design Matrix
The software executes the following 9 trials:

| Run | Factor A: TCP Algorithm | Factor B: Bandwidth | Factor C: Delay |
|:---:|:-----------------------:|:-------------------:|:---------------:|
|  1  |          Reno           |      100 Mbps       |      10 ms      |
|  2  |          Reno           |      500 Mbps       |      50 ms      |
|  3  |          Reno           |     1000 Mbps       |     100 ms      |
|  4  |          Cubic          |      100 Mbps       |      50 ms      |
|  5  |          Cubic          |      500 Mbps       |     100 ms      |
|  6  |          Cubic          |     1000 Mbps       |      10 ms      |
|  7  |           BBR           |      100 Mbps       |     100 ms      |
|  8  |           BBR           |      500 Mbps       |      10 ms      |
|  9  |           BBR           |     1000 Mbps       |      50 ms      |

---

## 3. Response Variables

For each run, the software measures three key network responses:
1. **Throughput (Mbps)**: The average rate of successful data delivery over the 10-second test.
2. **Throughput Variance**: The variance ($\sigma^2$) of the 1-second interval throughput measurements. This represents the **stability** of the connection; a lower variance means a more stable, predictable flow.
3. **Retransmission Rate (%)**: Calculated as:
   $$\text{Retransmission Rate (\%)} = \frac{\text{Total Retransmissions}}{\text{Total Bytes Sent} / \text{MSS}} \times 100$$
   This indicates the percentage of packets that had to be resent due to loss or congestion, showing the efficiency of the protocol.

---

## 4. How to Run the Software

The software features an intelligent **Mock Mode**. If run on a non-Linux system or without root privileges, it will simulate the physical experiments using realistic physical models, enabling you to test the complete web interface, view the charts, and export CSV data directly on Windows.

### Option A: Running on Windows/macOS (Mock Mode)

1. Ensure you have Python 3 installed.
2. Install the Python dependencies:
   ```bash
   pip install flask pandas numpy
   ```
3. Run the script:
   ```bash
   python tcp_regime_sim.py
   ```
4. Open your web browser and navigate to:
   [http://localhost:5000](http://localhost:5000)
5. Click **Initiate Emulation**. The terminal will simulate the runs, draw the Main Effects Plots, and allow you to download the CSV.

---

### Option B: Running on Linux with Mininet (Physical Emulation)

To run actual network emulations with virtual hosts, switches, and traffic control:

1. Copy the project folder to your Mininet VM or physical Linux machine.
2. Make the setup script executable and run it as root:
   ```bash
   chmod +x setup.sh
   sudo ./setup.sh
   ```
   *This script installs Mininet, iperf3, Flask, Pandas, and loads the BBR kernel module.*
3. Run the emulation software with root privileges:
   ```bash
   sudo python3 tcp_regime_sim.py
   ```
4. Open your web browser (either on the Linux machine or from your Windows host pointing to the Linux VM's IP address) at:
   `http://<linux_ip>:5000`
5. Click **Initiate Emulation** to start the physical Mininet tests. The backend will configure the kernel namespaces, set up traffic control delays, run `iperf3` client/servers, and parse the network sockets in real-time.

---

## 5. Analyzing Data in Minitab or SPSS (ANOVA)

Once the simulation completes, click the **Download CSV for Minitab/SPSS** button on the dashboard to download `tcp_regime_results.csv`.

### Step-by-Step ANOVA in Minitab:
1. Open **Minitab**.
2. Go to **File > Open** and select `tcp_regime_results.csv`.
3. Select **Stat > ANOVA > General Linear Model > Fit General Linear Model**.
4. In the **Responses** box, enter the response variables you want to analyze:
   - `Throughput_Mbps`
   - `Throughput_Variance`
   - `Retransmission_Rate_Pct`
5. In the **Factors** box, enter the three experimental factors:
   - `TCP_Algorithm`
   - `Bandwidth_Mbps`
   - `Delay_ms`
6. Click **OK**.
7. **Interpret the Output**:
   - **p-values**: In the Analysis of Variance table, look at the p-value for each factor. A $p < 0.05$ indicates that the factor has a statistically significant effect on the response at a 95% confidence level.
   - **Main Effects Plot**: Select **Stat > ANOVA > General Linear Model > Factorial Plots**. Select your factors and responses, then click OK. Minitab will generate a Main Effects Plot showing the mean response at each factor level. (This plot will match the interactive line charts displayed under the **Taguchi Main Effects Analysis** tab in the TCP OptiFlow web dashboard!).
