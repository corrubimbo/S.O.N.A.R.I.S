# S.O.N.A.R.I.S
Premium high-quality Bluetooth Stereo Speaker with a Built-in screen. Multi-purpose speaker with a desktop design and high portability. Ultimate vibe machine
## About
A bit of information about me is that once I get invested in something, it is VERY HARD for me to lose track of it. Before starting this project, I had gotten very interested in speakers, audiophile setups, and enclosure design. This project was the perfect outlet for me to express my interest in designing a speaker, not a crappy one that just emits audio but feels like a real product that is visually pleasing to look at. I currently use a JBL Go Pro 4, a crappy mono channel speaker that is built for portability above all, and while it was a step up from my laptop speakers, it was still bad speakers. This project was my best chance to make FAR better speakers than I had before, but I wanted something unique, not something that looks like I could buy on the market. I stumbled on visualizers while looking at people's custom Rices (custom design of a Linux distro) and thought that would be a cool addition to my speaker. So I settled on my idea: a cool Bluetooth stereo speaker that has a screen in the middle that displays audio information and a visualizer. I originally wanted to also implement a Mag-Safe charger on the top of the speaker (since it solves another problem I face), but that was hard to implement and very expensive, so I removed it from my design and went with this speaker. In order to use it, you first connect it to your phone using Bluetooth (doesn't support plug and play) under the name SONARIS and play the audio you want to play; no other configuration required from the build. Two Bluetooth protocols, A2DP and AVRCP, are automatically implemented with Bluetooth, letting both metadata like album art, audio, track, and artist be sent (A2DP), and allowing scripts to send signals back to the Bluetooth device like play, pause, next, and previous (AVRCP).
## Design 

<img width="1020" height="649" alt="image" src="https://github.com/user-attachments/assets/957197cc-e08a-4edf-a405-bdc8a3cf59a0" />

<img width="1154" height="682" alt="image" src="https://github.com/user-attachments/assets/f018e143-0f7b-4cfe-a6c7-9a8b51725f5f" />

<img width="1155" height="783" alt="image" src="https://github.com/user-attachments/assets/e2807e1a-badf-473a-b4ec-e15e95d552f5" />

The speaker uses a curved matte light-gray concrete frame with a PETG filament casing covered with textured wood-vinyl. The casing covers 5 chambers: left and Right woofer chambers, Left and Right tweeter chambers, and the center chamber. Inside the woofer chambers, there is a perfect-fit slot for the driver, with the interior walls covered with acoustic foam (green block). A small hole will be in the top interior wall, allowing the speaker wires to enter the enclosure before being sealed airtight with silicone. On top of the woofer chamber lies the tweeter chamber; the tweeter chamber has a perfect-fit-slot for the tweeter and space to store the crossover network for that channel. A hole near the bottom will be cut in order to let the speaker wires from the crossover network also reach the woofer, before being sealed. The screws will all be sealed with M3 heat-inserts and M3 screws. The center chamber will have a rectangular cutout for the monitor, and behind the monitor will be space for the remaining electronics such as batteries, amp, USB-C board, etc.

## Schematic

<img width="1222" height="849" alt="image" src="https://github.com/user-attachments/assets/4e89b046-9c86-4c9e-b77b-c2f711f0cd8e" />

Using a USB-C PD board configured to 4S, a USB-C cable is able to power the entire speaker. Power from the USB-C travels into the BMS and 4S Battery cells; the BMS monitors the battery cells' health while they charge and discharge. From the battery, they take two routes: they directly power the amp and power the Raspberry Pi. First, the power goes through an SPST switch (Power on and off) and a 5A fuse; they diverge before entering a buck converter module that reduces the voltage to a safe limit for the Raspberry Pi. A Micro-USB pigtail is used from the output of the buck converter to power the Raspberry Pi with the protection that is included in the Micro-USB port. From here, the Raspberry Pi powers the DAC and the monitor. The DAC is connected to the Pi's DIN, BCK, and LRCK pins on the Raspberry Pi while outputting the AGND, LOUT, and ROUT to the amp. From the amp, powered with the 16.8 V from the battery, both left and right channels go through the crossover network before reaching the woofer and tweeter and emitting audio.

## Software and Visualizer Script
The software controls both the display and the controls that will serve as media controls. AVRCP protocol will allow for my button daemon to send signals to the Bluetooth device so my Pause/Play, Next, and Previous buttons work. A2DP will be the main protocol for the Raspberry Pi to play the audio, using PipeWire and the Raspberry Pi as a Bluetooth sink; it can play audio that will be sent through Bluetooth. I will also add a rotary encoder with a built-in SPST switch; the encoder controls the volume with each pulse (24 pulses per revolution), increasing or decreasing the volume by 5%. The built-in SPST switch in the encoder will turn off the screen (not the audio), functioning as a manual battery saver.

https://github.com/user-attachments/assets/bdc164bf-ed7d-49ca-9e82-6e2769f0c6df

The visualizer will be displayed on a headless Lite OS setup; it works by displaying rings with thicknesses at set distances that "pulse" up and down from its designated frequency range. It uses C.A.V.A's optimized FFT data to produce the "ripples". It has an Apple Music-type background that blurs and warps over time. To sell the illusion of a ripple, the rings diffract simulated light to create diffraction, and to simulate height, there is shine and shadows for each ring, creating the illusion of light being produced from the top-right corner. for more information about the visualizer, look at the [Reference](software/ripple_reference.md) file in the software folder.

## Bill of Materials

| Part | Qty | Unit | Total | Retailer | Status |
|---|---:|---:|---:|---|---|
| DMA80-4 3" Woofer | 2 | $16.98 | $33.96 | Parts Express | Not Owned |
| ND16FA-4 5/8" Tweeter | 2 | $8.98 | $17.96 | Parts Express | Not Owned |
| DMA80-PR Passive Radiator | 2 | $9.49 | $18.98 | Parts Express | Not Owned |
| LW18-15 0.15mH Inductor | 4 | $5.00 | $20.00 | Parts Express | Not Owned |
| DMPC 4.7uF Capacitor | 6 | $1.69 | $10.14 | Parts Express | Not Owned |
| 10uF NP Capacitor | 2 | $1.09 | $2.18 | Parts Express | Not Owned |
| DNR 6.0Ω Resistor | 4 | $1.25 | $5.00 | Parts Express | Not Owned |
| DNR 2.0Ω Resistor | 2 | $1.25 | $2.50 | Parts Express | Not Owned |
| Raspberry Pi Zero 2 W | 1 | $14.99 | $14.99 | Micro Center | Owned |
| 32GB microSD | 1 | $22.99 | $22.99 | Amazon | Owned |
| 7" 1024x600 LCD Monitor | 1 | $29.58 | $29.58 | AliExpress | Owned |
| PCM5102A DAC Board | 1 | $11.99 | $11.99 | Amazon | Owned |
| Mini-HDMI Ribbon Cable | 1 | $6.99 | $6.99 | Amazon | Not Owned |
| Breakable Header Pins | 1 | $2.62 | $2.62 | AliExpress | Owned |
| Samsung 35E 18650 Cell | 4 | $4.99 | $19.96 | 18650 Battery Store | Not Owned |
| HiLetgo 4S 30A BMS | 1 | $7.49 | $7.49 | Amazon | Not Owned |
| IP2368 PD Charger | 1 | $19.99 | $19.99 | Newegg | Owned |
| 5A Buck Regulator | 1 | $5.99 | $5.99 | Amazon | Not Owned |
| Micro-USB Pigtail | 2 | $4.99 | $9.98 | Amazon | Not Owned |
| DC Rocker Switch | 1 | $5.99 | $5.99 | Amazon | Not Owned |
| Battery Wrap | 1 | $1.31 | $1.31 | AliExpress | Owned |
| ATO Blade Fuse Holder | 1 | $5.09 | $5.09 | Amazon | Not Owned |
| 5A ATO Blade Fuses | 1 | $4.99 | $4.99 | Amazon | Not Owned |
| 22 AWG Speaker Wire | 1 | $5.18 | $5.18 | Amazon | Not Owned |
| 4S Battery Holder | 1 | $9.95 | $9.95 | Amazon | Not Owned |
| Tact Push Buttons | 1 | $2.69 | $2.69 | AliExpress | Owned |
| Jumper Wires | 1 | $1.63 | $1.63 | AliExpress | Owned |
| Pi Heatsink Kit | 1 | $2.79 | $2.79 | AliExpress | Owned |
| Capacitor Assortment Kit | 1 | $9.99 | $9.99 | Amazon | Not Owned |
| 3A Glass Fuses | 1 | $4.99 | $4.99 | Amazon | Not Owned |
| 3A Inline Fuse Holder | 1 | $5.99 | $5.99 | Amazon | Not Owned |
| M3 Heat-Set Inserts | 1 | $3.52 | $3.52 | AliExpress | Owned |
| M3 Screw Set | 1 | $0.99 | $0.99 | AliExpress | Owned |
| M2.5/M3 Nylon Spacer Kit | 1 | $9.99 | $9.99 | Amazon | Not Owned |
| Perfboard Kit | 1 | $7.99 | $7.99 | Amazon | Not Owned |
| 14 AWG Wire | 1 | $9.88 | $9.88 | Amazon | Not Owned |
| Acoustic Damping Foam | 1 | $11.50 | $11.50 | Parts Express | Not Owned |
| WONDOM AAM4 Amp | 1 | $9.99 | $9.99 | Amazon | Not Owned |
| Soldering Iron Kit | 1 | $24.99 | $24.99 | Amazon | Owned |
| XTC-3D | 1 | $19.99 | $19.99 | Amazon | Not Owned |
| Kapton Tape | 1 | $3.12 | $3.12 | AliExpress | Owned |
| Kraken Bond Silicone | 1 | $7.19 | $7.19 | Amazon | Not Owned |
| EVA Foam Gasket Tape | 1 | $1.56 | $1.56 | AliExpress | Owned |
| 3kg Black PETG Filament | 1 | $39.99 | $39.99 | Amazon | Not Owned |
| Adhesive Wood Vinyl | 1 | $4.99 | $4.99 | Amazon | Not Owned |
| Silver Volume Knob | 1 | $9.99 | $9.99 | Amazon | Not Owned |
| Rotary Encoder (PEC11R) | 1 | $2.23 | $2.23 | Mouser | Not Owned |
| AR Glass Fiber | 1 | $11.99 | $11.99 | Amazon | Not Owned |
| Cement All Concrete | 1 | $21.97 | $21.97 | Home Depot | Not Owned |
| **Total (Not Owned and no shipping + no tax)** | | | **$380.99** | | |
| **Shipping + Tax Estimate** | | | **$40.65** | | |
| **Total (Just Now Owned)** | | | **$421.64** | | |
