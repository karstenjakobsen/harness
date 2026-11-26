# Invoice checkout fixture

`invoice_total(items)` must multiply each decimal unit price by its integer
quantity and sum the lines without losing decimal precision. An empty invoice
has total zero. The committed implementation deliberately ignores quantities.

Run the existing acceptance test, without changing it:

```sh
python3 -m unittest discover -s tests -p check_invoice.py -v
```

The worker assignment requires an implementation fix and an ordinary Git patch
including `WORKER_TEST_REPORT.txt` with the output of that command. The owner
applies the saved patch to a clean checkout of the recorded base and runs the
same unchanged test again.
