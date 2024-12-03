TAG_SETS = [set("ABC"), set("BCD"), set("AB"), set("DEF"), set("LMNOP")]


class TestOverlapTable:
    def _tables_equal(self, table0, table1):
        """Equality test for two ``OverlapTable``s"""
        return table0.n_sets == table1.n_sets and (
            list(table0.pairs_overlaps()) == list(table1.pairs_overlaps())
        )
