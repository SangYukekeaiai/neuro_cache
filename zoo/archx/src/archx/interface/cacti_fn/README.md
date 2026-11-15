```cacti_fn``` interface for Archx.

## What it is
```cacti_fn``` runs FN-CACTI ([github.com/marg-tools/FN-CACTI](https://github.com/marg-tools/FN-CACTI), TVLSI 2021). FN-CACTI is a patch on USC PCACTI ([sportlab.usc.edu](https://sportlab.usc.edu), ```pcacti.tar```). It adds FinFET and NC-FinFET models with hardcoded 14 nm data. Stock FN-CACTI deletes PCACTI's XML device loader. This copy restores that loader, so more device nodes run.

The interface models scratch RAM (class ```sram```) and caches (class ```cache```). Cache output is the whole-cache total (data + tag), with ECC off. DRAM goes through ```cacti7```.

## Provenance and build
The C++ source in ```include/cacti_fn``` comes from the official USC ```pcacti.tar``` and the upstream ```fncacti.patch```. It follows the recipe in upstream ```fncacti_patch.sh```. That script deletes ```xmls/```, ```xmlParser.cc``` and ```xmlParser.h```. We re-added them from PCACTI.

```cacti_fn.py``` runs a per-host binary named ```cacti-<system>-<machine>```, for example ```cacti-Darwin-arm64```. When the binary is absent, it runs ```make all``` in ```include/cacti_fn``` and renames the result. This is the same scheme as ```cacti7```.

Two build fixes differ from upstream:
1. ```cacti.mk``` reads the compiler target with ```$(CXX) -dumpmachine```. The gate keeps ```-msse2 -mfpmath=sse``` and ```-gstabs+``` for x86_64 targets and drops them for native arm64 clang.
2. ```nuca.cc``` drops the default argument ```= &(g_tp.peri_global)``` from the ```Nuca::Nuca``` definition (line 53).

## Changes vs stock FN-CACTI
1. New config keys in ```io.cc```, backed by three new ```InputParameter``` fields in ```cacti_interface.h``` (lines 303-305): ```is_near_threshold```, ```use_device_xml``` and ```sram_cell_file```. ```-device file``` sets all four device XML paths and sets the ```use_device_xml``` flag. ```-sram cell file``` sets the SRAM cell XML. Without ```-device file```, ```default_device_files()``` picks a file by node and transistor. The 14 nm FinFET case returns early and keeps the hardcoded data.
2. Gated 14 nm data. The four Vdd-indexed Ioff tables and the 14 nm force in ```reconfigure()``` run only when ```!use_device_xml```. The list below gives each location.
3. Parser bug fix. Upstream writes ```else if(vdd = 0.7)``` in the parser Ioff tables. That is an assignment and always true, so any Vdd other than 0.8 V became 0.7 V. It is now ```vdd == 0.7```.
4. Merged device models in ```technology.cc```. The hardcoded 14 nm FinFET and NC-FinFET block stays. PCACTI's XML device block is added for other nodes. It assumes Wfin equals the fin thickness ```t_si```. It copies the CAM cell rule (SRAM widths, 2x area and aspect ratio) and the FN McPAT scaling constants from the 14 nm block.
5. Voltage sweep on the XML path. In ```Ucache.cc```, ```update_dvs()``` re-selects the XML voltage and reloads the SRAM cell file for each DVS voltage. The XML path rejects NC-FinFET, which has data only in the 14 nm block.

The gated Ioff tables are in these functions of ```io.cc```:
- ```parse_cfg``` (line 408)
- ```cacti_interface(InputParameter*)``` (line 3153)
- ```init_interface``` (line 3327)
- ```reconfigure``` (line 3439, the 14 nm and ASAP7 force at line 3529)

14 nm FinFET output is byte-identical to stock FN-CACTI on ```configs/2MB_fin.cfg``` and ```configs/2MB_nc.cfg```. This is verified with ```cmp``` on the arm64 build, against pre-merge baselines from the same vendored tree.

## Supported devices
| technology (nm) | transistor | voltages (V) | default (V) | device file |
|---|---|---|---|---|
| 14 | finfet | 0.2 to 0.8, 0.1 steps | 0.7 | hardcoded |
| 7 | finfet | 0.45, 0.30, 0.7 | 0.45 | ```xmls/devices/finfet_7nm_std.xml```, ```finfet_7nm_0p7.xml``` for 0.7 |
| 14 | cmos | 0.80, 0.55 | 0.80 | ```xmls/devices/cmos_14nm_std.xml``` |
| 22 | cmos | 0.80 | 0.80 | ```xmls/devices/cmos_22nm_hp.xml``` |

Neither tool ships data for 5 nm FinFET or 16 to 90 nm CMOS. These nodes stop with an error. There is no voltage interpolation: an unlisted voltage stops with an error. The table lives in ```device_configs``` in ```cacti_fn.py```.

Both classes use ```technology``` and ```frequency```. Class ```sram``` uses ```width``` (bits), ```depth```, and ```bank```. Class ```cache``` uses ```size``` (bits), ```width``` (cache line bits), ```associativity``` (an integer power of two >= 1), and ```bank```. Cache size must be a multiple of 8 bits. Its byte count must be divisible by line bytes * associativity * bank. Line width rounds up to whole bytes. Fully associative caches (associativity 0) are not accepted. Cache uses one read-write port and no exclusive ports. Its optional ```access_mode``` is ```normal``` (default), ```sequential```, or ```fast```. SRAM uses one exclusive read port, one exclusive write port, no read-write ports, and ```normal``` access.

Optional keys: ```wire_technology``` (nm, defaults to ```technology```), ```voltage```, ```transistor``` (defaults to ```finfet```), ```device_file```, ```sram_cell_file```. The two file paths are relative to ```include/cacti_fn```. ```sram.cfg``` is the base config for both classes. It holds fixed knobs, for example ASAP7 wires and ```Add ECC``` false. The wrapper sets memory type, associativity, tag size (```default```), ports, and access mode.

## Model caveats
The 7 nm path puts PCACTI device data inside FN-CACTI's circuit model. At 4 MB, 4 banks and 0.45 V, it reports about +7% read energy, +7% area and +27% leakage vs native PCACTI. Two FN-CACTI models cause the gap. First, ECC columns count as cells; this has zero effect with ```Add ECC``` false. Second, the leakage width is 2 x Hfin + Wfin, not 2 x Hfin.

```finfet_7nm_0p7.xml``` is a first-order scale of the 0.45 V point, not measured data. Its super-threshold Vdd is set to 0.7. Ion scales by the alpha-power law (alpha 1.3, Vth 0.235 V), a factor k_on = 2.726. Ioff scales by DIBL (40 mV/V, S 68 mV/dec), a factor k_off = 1.403. Sense-amp energy scales by Vdd squared. Sense-amp delay scales by (Vdd ratio) / k_on = 0.571. The near-threshold (0.3 V) values are unchanged. Replace this file with TCAD or SPICE data before publication.

The SRAM cell file names its own device file for each cell transistor. So a user ```sram_cell_file``` at 0.7 V loads the cell Ioff from that device, not from ```finfet_7nm_0p7.xml```. The default cell file loads the cell device from the selected device file.

## Caching
Each SRAM run writes ```<name>.sram.width<W>.depth<D>.bank<B>.tech<T>.<signature>.cacti_fn.cfg```. Cache uses ```<name>.cache.size<S>.width<W>.assoc<A>.bank<B>.tech<T>.<signature>.cacti_fn.cfg```. Each run also writes a ```.rpt``` report and a ```.flag``` file in ```output_dir```. The signature is a hash of the memory type, the node, all query knobs and the contents of ```sram.cfg``` and the XML device and cell files used by the run. A present ```.flag``` file skips the FN-CACTI run. This is the same scheme as ```cacti7```.
