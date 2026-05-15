# Future plans

The high-payoff patterns from the original list (forms Meta dicts,
CBV inherited attrs, m2m.through, RunPython.noop, iommi `attr=`
bridging, iommi callable refinables, annotate/aggregate aliases,
`get_user_model()`, custom QuerySet methods) are all in. What's left
is speculative — only worth doing once a concrete user request lands.

## Possible next steps

- **annotate alias resolution across statements.** Currently we only
  pick up aliases declared in the same expression chain. A
  ``qs = User.objects.annotate(n=Count('articles'))`` followed by
  ``qs.filter(n__gt=0)`` on the next line still flags ``n``. Adding
  flow analysis through the local-variable assignment would close
  that gap. Cost: another pass through the AST, plus the usual
  same-function-scope caveats.

- **Manager-to-QuerySet linkage.** We currently union all workspace
  QuerySet method names rather than linking each ``objects =
  MyQuerySet.as_manager()`` to its specific QuerySet. Precise linkage
  would let completion surface only the *right* methods on a given
  model's manager.

- **Signature checking for callable refinables.** The
  ``iommi-callable-expected`` rule catches string-instead-of-name
  typos but not "this callable doesn't accept the kwargs iommi will
  pass." Real signature validation needs runtime introspection or a
  hand-curated table.
