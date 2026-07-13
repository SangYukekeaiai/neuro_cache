// eventsim — discrete-event NoC latency simulator CLI.
//
// Usage:
//   eventsim <tc.csv> --X <X> --Y <Y> --dram-port <id> --dram-latency <n>
//
// Prints a one-line JSON summary to stdout:
//   {"total_cycles":N,"unicast_cycles":N,"multicast_cycles":N,
//    "count_cycles":N,"dram_cycles":N}
#include <cstdlib>
#include <iostream>
#include <string>

#include "EventSim.h"
#include "NoC.h"
#include "Transaction.h"

struct Args {
    std::string csv_path;
    int X = -1, Y = -1;
    int dram_port = -1;
    long long dram_latency = -1;
};

Args parse_args(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: eventsim <tc.csv> --X <X> --Y <Y> "
                     "--dram-port <id> --dram-latency <n>\n";
        std::exit(2);
    }

    Args a;
    a.csv_path = argv[1];

    for (int i = 2; i < argc; ++i) {
        std::string flag = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) {
                std::cerr << "eventsim: missing value for " << flag << "\n";
                std::exit(2);
            }
            return argv[++i];
        };
        if (flag == "--X") a.X = std::stoi(next());
        else if (flag == "--Y") a.Y = std::stoi(next());
        else if (flag == "--dram-port") a.dram_port = std::stoi(next());
        else if (flag == "--dram-latency") a.dram_latency = std::stoll(next());
        else {
            std::cerr << "eventsim: unknown flag " << flag << "\n";
            std::exit(2);
        }
    }

    if (a.X <= 0 || a.Y <= 0 || a.dram_port < 0 || a.dram_latency < 0) {
        std::cerr << "eventsim: --X, --Y, --dram-port, --dram-latency are all required\n";
        std::exit(2);
    }
    return a;
}

int main(int argc, char** argv) {
    Args args = parse_args(argc, argv);

    try {
        std::vector<Transaction> tcs = parse_csv(args.csv_path);
        NoC noc(args.X, args.Y);
        SimResult res = simulate(tcs, noc, args.dram_port, args.dram_latency);

        std::cout << "{"
                  << "\"total_cycles\":" << res.total_cycles << ","
                  << "\"unicast_cycles\":" << res.unicast_cycles << ","
                  << "\"multicast_cycles\":" << res.multicast_cycles << ","
                  << "\"count_cycles\":" << res.count_cycles << ","
                  << "\"dram_cycles\":" << res.dram_cycles << "}" << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "eventsim: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}
