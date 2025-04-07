# invokeai-node-docs
Node repository documentation generator for InvokeAI

This can be run with the command:
```
python node-docs.py path/to/nodes/repo/
```

If you are running this from *inside* the nodes repo folder, you must specify:
```
python node-docs.py ../repo/
```
rather than just `.`.

If you want to use a `node-docs.yaml` file to add additional markdown
sections beyond the automatically generated ones, place that file
directly in your repository folder  [see the included example].