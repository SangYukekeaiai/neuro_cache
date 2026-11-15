```csv_cmos``` interface for Archx.

## Usage
```csv_cmos_extra.py``` generates .csv files from synthesis and place-and-route reports.

All inputs and outputs are under the ```csv_cmos``` directory.

### Input
1. ```syn_pnr_rpt``` folder with a structure of ```syn_pnr_rpt/<technode>/<module>/<module>_DETAILS.rpt```, which is generated from [auto_syn_pnr](https://github.com/UnaryLab/auto_syn_pnr). Change the ```technology``` and ```frequency``` in the ```__main__``` to generate correct results.
2. ```param.yaml``` file that defines the parameters for interpolation for each module. The attached file is just an example, and needs to be adapted for use.

### Output
1. ```syn_pnr_csv``` with a structure of ```syn_pnr_csv/<module>.csv```. All generated .csv files shall be moved into ```include/csv``` for interface query.
