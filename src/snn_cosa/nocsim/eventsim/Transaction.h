// Transaction.h — parses the tc.csv format written by core/transaction.py.
//
// Row grammar (one transaction = one comment line + one data line):
//   # <annotation>
//   tc_id,actor_id,op,size,src,dest,dep
// where src/dest/dep are space-separated integer lists (dest/dep may be
// empty). op: 0 UNICAST, 1 MULTICAST, 2 COUNT.
#pragma once

#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct Transaction {
    int tc_id;
    int actor_id;
    int op;
    long long size;
    std::vector<int> srcs;   // always [actor_id], kept for CSV fidelity
    std::vector<int> dests;  // empty for COUNT
    std::vector<int> deps;   // tc_ids that must finish first
};

inline std::vector<int> parse_int_list(const std::string& s) {
    std::vector<int> out;
    std::istringstream iss(s);
    int v;
    while (iss >> v) out.push_back(v);
    return out;
}

inline std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::string cur;
    for (char c : line) {
        if (c == ',') {
            fields.push_back(cur);
            cur.clear();
        } else {
            cur.push_back(c);
        }
    }
    fields.push_back(cur);
    return fields;
}

inline std::vector<Transaction> parse_csv(const std::string& path) {
    std::ifstream in(path);
    if (!in.is_open()) {
        throw std::runtime_error("cannot open " + path);
    }

    std::vector<Transaction> result;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;

        auto fields = split_csv_line(line);
        if (fields.size() != 7) {
            throw std::runtime_error("malformed CSV row (expected 7 fields, got " +
                                      std::to_string(fields.size()) + "): " + line);
        }

        Transaction tc;
        tc.tc_id    = std::stoi(fields[0]);
        tc.actor_id = std::stoi(fields[1]);
        tc.op       = std::stoi(fields[2]);
        tc.size     = std::stoll(fields[3]);
        tc.srcs     = parse_int_list(fields[4]);
        tc.dests    = parse_int_list(fields[5]);
        tc.deps     = parse_int_list(fields[6]);
        result.push_back(std::move(tc));
    }
    return result;
}
