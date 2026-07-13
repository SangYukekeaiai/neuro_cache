// NoC.h — C++ port of core/noc.py's coordinate/routing model.
//
// Mirrors get_xy() / _hops_single() / manhattan() exactly so eventsim's
// link set matches what the Python frontend already computes for the
// static unicast_hops/multicast_hops metrics.
#pragma once

#include <algorithm>
#include <cmath>
#include <tuple>
#include <utility>
#include <vector>

// Directed link, endpoints as (x0,y0) -> (x1,y1).
using Link = std::tuple<int, int, int, int>;

struct NoC {
    int X, Y;

    NoC(int X_, int Y_) : X(X_), Y(Y_) {}

    std::pair<int, int> get_xy(int id) const {
        return {id % X, id / X};
    }

    int manhattan(int src, int dest) const {
        auto [sx, sy] = get_xy(src);
        auto [dx, dy] = get_xy(dest);
        return std::abs(dx - sx) + std::abs(dy - sy);
    }

    // Ordered list of directed links on the XY route src->dest:
    // all X distance first (horizontal), then all Y distance (vertical).
    std::vector<Link> hops_single(int src, int dest) const {
        std::vector<Link> links;
        auto [sx, sy] = get_xy(src);
        auto [dx, dy] = get_xy(dest);

        int x_step = (dx > sx) ? 1 : -1;
        for (int x = sx; x != dx; x += x_step) {
            links.emplace_back(x, sy, x + x_step, sy);
        }
        int y_step = (dy > sy) ? 1 : -1;
        for (int y = sy; y != dy; y += y_step) {
            links.emplace_back(dx, y, dx, y + y_step);
        }
        return links;
    }
};
