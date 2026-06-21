/// Bounds the live trace-span lists so a long build doesn't grow them without
/// limit (memory) and so PlainThoughtFormatter doesn't re-walk an ever-growing
/// list every frame (CPU). Drops the OLDEST spans beyond [max], in place.
///
/// The live feed only needs a tail window — older cards have scrolled away and
/// the durable record lives in the OTEL traces / artifacts.
const int kMaxLiveSpans = 400;

List<T> capLiveSpans<T>(List<T> spans, {int max = kMaxLiveSpans}) {
  if (spans.length > max) {
    spans.removeRange(0, spans.length - max);
  }
  return spans;
}
