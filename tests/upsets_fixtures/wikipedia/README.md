`synthetic_draw.wikitext` is **synthetic**: invented players in the markup Wikipedia's tennis draw articles use
(a "Seeds" heading with a numbered list of player links, and bracket templates with `|RD1-seedNN=` /
`|RD1-teamNN=`). It was written by hand because en.wikipedia.org isn't reachable from the cloud session
(network policy, 2026-10-28). Once the owner allowed the domain (same day), the MediaWiki API answered HTTP 429
"too many requests" to every call from the cloud sessions' shared IP (Lead's and Upsets', 1-4 calls each), so it is
still synthetic. Replace it with a trimmed copy of one real draw (CC BY-SA; note the article
and revision here) once the domain is allowed.
