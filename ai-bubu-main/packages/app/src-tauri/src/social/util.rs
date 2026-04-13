pub fn truncate_str(s: String, max: usize) -> String {
    if s.chars().count() > max {
        s.chars().take(max).collect()
    } else {
        s
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_truncation_needed() {
        assert_eq!(truncate_str("abc".into(), 5), "abc");
    }

    #[test]
    fn exact_length() {
        assert_eq!(truncate_str("abcde".into(), 5), "abcde");
    }

    #[test]
    fn truncates_ascii() {
        assert_eq!(truncate_str("abcdef".into(), 3), "abc");
    }

    #[test]
    fn truncates_unicode() {
        assert_eq!(truncate_str("你好世界测试".into(), 4), "你好世界");
    }
}
