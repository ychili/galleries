TAG_SETS = [set("ABC"), set("BCD"), set("AB"), set("DEF"), set("LMNOP")]


class TestOverlapTable:
    def _tables_equal(self, table0, table1):
        """Equality test for two ``OverlapTable``s

        Compares on private attribute _table, so don't rely on this.
        """
        # pylint: disable=protected-access
        return table0.n_sets == table1.n_sets and table0._table == table1._table
