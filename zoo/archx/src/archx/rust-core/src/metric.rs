use indexmap::IndexMap;
use serde::{Deserialize, Serialize};

/// A single {value, unit} metric — for events and single-operation modules.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SingleMetric {
    pub value: f64,
    pub unit: String,
}

/// Metric storage for one (metric_name) slot on a node.
/// Single: normal event node or single-op module  → {value, unit}
/// MultiOp: module with named operations (e.g. sram read/write) → {op → {value, unit}}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum MetricValue {
    Single(SingleMetric),
    MultiOp(IndexMap<String, SingleMetric>),
}

impl MetricValue {
    pub fn as_single(&self) -> &SingleMetric {
        match self {
            MetricValue::Single(s) => s,
            MetricValue::MultiOp(_) => panic!("called as_single on MultiOp metric"),
        }
    }

    pub fn as_single_mut(&mut self) -> &mut SingleMetric {
        match self {
            MetricValue::Single(s) => s,
            MetricValue::MultiOp(_) => panic!("called as_single_mut on MultiOp metric"),
        }
    }

    pub fn is_single(&self) -> bool {
        matches!(self, MetricValue::Single(_))
    }

    pub fn is_multi_op(&self) -> bool {
        matches!(self, MetricValue::MultiOp(_))
    }

    pub fn op_names(&self) -> Vec<String> {
        match self {
            MetricValue::MultiOp(m) => m.keys().cloned().collect(),
            MetricValue::Single(_) => vec![],
        }
    }

    pub fn get_op_value(&self, op: &str) -> Option<f64> {
        match self {
            MetricValue::MultiOp(m) => m.get(op).map(|s| s.value),
            MetricValue::Single(_) => None,
        }
    }
}

/// All metrics for one node: metric_name → MetricValue
pub type NodeMetrics = IndexMap<String, MetricValue>;

/// Format an `f64` the way Python's `str()`/`repr()` would, so the Rust log
/// messages match the original pure-Python f-strings character for character.
/// Two differences from Rust's `{}` are corrected here: integer-valued floats
/// keep a trailing `.0` (Python `1.0` vs Rust `1`), and the switch to
/// scientific notation uses Python's thresholds (`decimal_point <= -4` or
/// `> 16`) with a signed, ≥2-digit exponent (e.g. `1e-05`, `1e+16`).
pub fn fmt_py(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x < 0.0 { "-inf".to_string() } else { "inf".to_string() };
    }

    // Rust's `{:e}` yields the shortest round-tripping mantissa in scientific
    // form (e.g. 1.0 -> "1e0", 12.34 -> "1.234e1", 1e-5 -> "1e-5"), matching
    // Python's shortest-repr digits.
    let sci = format!("{:e}", x);
    let (mantissa, exp_str) = sci.split_once('e').expect("LowerExp always has 'e'");
    let exp: i32 = exp_str.parse().expect("valid exponent");

    let negative = mantissa.starts_with('-');
    let mantissa_abs = mantissa.trim_start_matches('-');
    let digits: String = mantissa_abs.chars().filter(|&c| c != '.').collect();

    // Number of digits to the left of the decimal point in plain notation.
    let decimal_point = exp + 1;

    let body = if decimal_point <= -4 || decimal_point > 16 {
        // Exponential: d[.ddd]e±XX  (exponent sign always present, ≥2 digits).
        let disp_exp = decimal_point - 1;
        let mut s = String::new();
        s.push_str(&digits[..1]);
        if digits.len() > 1 {
            s.push('.');
            s.push_str(&digits[1..]);
        }
        s.push('e');
        s.push(if disp_exp < 0 { '-' } else { '+' });
        s.push_str(&format!("{:02}", disp_exp.abs()));
        s
    } else if decimal_point <= 0 {
        // 0.00ddd
        format!("0.{}{}", "0".repeat((-decimal_point) as usize), digits)
    } else if (decimal_point as usize) >= digits.len() {
        // ddd00.0
        format!("{}{}.0", digits, "0".repeat(decimal_point as usize - digits.len()))
    } else {
        // dd.ddd
        let dp = decimal_point as usize;
        format!("{}.{}", &digits[..dp], &digits[dp..])
    };

    if negative { format!("-{}", body) } else { body }
}

#[cfg(test)]
mod tests {
    use super::fmt_py;

    #[test]
    fn matches_python_repr() {
        assert_eq!(fmt_py(1.0), "1.0");
        assert_eq!(fmt_py(0.0), "0.0");
        assert_eq!(fmt_py(-0.0), "-0.0");
        assert_eq!(fmt_py(16.0), "16.0");
        assert_eq!(fmt_py(100.0), "100.0");
        assert_eq!(fmt_py(1.5), "1.5");
        assert_eq!(fmt_py(12.34), "12.34");
        assert_eq!(fmt_py(0.1), "0.1");
        assert_eq!(fmt_py(0.0001), "0.0001");
        assert_eq!(fmt_py(0.00001), "1e-05");
        assert_eq!(fmt_py(1.23e-10), "1.23e-10");
        assert_eq!(fmt_py(1e15), "1000000000000000.0");
        assert_eq!(fmt_py(1e16), "1e+16");
        assert_eq!(fmt_py(1.5e20), "1.5e+20");
        assert_eq!(fmt_py(-2.5), "-2.5");
    }
}
