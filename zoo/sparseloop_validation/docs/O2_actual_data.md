# Actual-data density input

The MICRO’22 artifact pins Timeloop `1eb0fd0a62fea1f3df4580a1b6c7ae6238772fbb` through infrastructure `4a958cf1311609765179c1f5500ae19d44f0432f`. This is the S1 backend. The current infrastructure pin, Timeloop `32370826fdf1aa3c8deb0c93e6b2a2fc7cf053aa`, lacks this density implementation and is not the execution backend.

The workload stanza is:

```yaml
problem:
  instance:
    densities:
      Inputs:
        distribution: real-data
        data_file_path: masks/input.txt
      Weights:
        distribution: fixed
        density: 1.0
```

`real-data.cpp:41–56` parses the file path. Lines 76–110 read non-whitespace characters, interpret `1` as present and other characters as absent, and require mask length to equal the projected tensor volume. Our exporter must validate only `0`/`1`; the upstream reader does not reject other characters. Lines 115–125 flatten the tensor with the **first projection coordinate varying fastest**. This is a full binary tensor mask, not a scalar density or a per-tile histogram. It computes tile occupancy by traversing the mask; it requires a single axis-aligned tensor region.

Source: [paper artifact](../vendor/micro22-sparseloop-artifact/README.md), [real-data implementation](../vendor/micro22-sparseloop-artifact/docker/accelergy-timeloop-infrastructure/src/timeloop/src/workload/density-models/real-data.cpp), [shipped actual-data workload](../vendor/micro22-sparseloop-artifact/workspace/2022.micro.artifact/evaluation_setups/fig12_eyerissv2_pe_setup/workload/mobilenet0.5-sparse/actual_data/L09.yaml).

The ingest retains the original four timestep bit arrays for each of the 23 selected samples, losslessly compressed. Scalar density measurements are diagnostics only: they cannot substitute for these masks. Padding and projection order must be checked explicitly when exporting convolution inputs. No Tier C workload has been executed.
