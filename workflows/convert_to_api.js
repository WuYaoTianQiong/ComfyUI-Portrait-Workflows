const fs = require('fs');

// Load V6
const v6 = JSON.parse(fs.readFileSync('【优化版V6】QWEN-AIO-DWPose-VNCCS-全开关.json', 'utf-8'));

// Build link lookup: link_id → [source_node_id, source_slot, dest_node_id, dest_slot, type]
const linkMap = {};
for (const link of v6.links) {
    linkMap[link[0]] = link;
}

// Build output slot info: node_id → [{name, type, links}]
const outputInfo = {};
for (const node of v6.nodes) {
    outputInfo[node.id] = node.outputs || [];
}

// Convert each node to API format
const api = {};

for (const node of v6.nodes) {
    const nodeEntry = {
        class_type: node.type,
        inputs: {}
    };

    // Process widget values - map them by position to input names
    const connectedInputs = (node.inputs || []).filter(i => i.link != null);
    const widgetInputs = (node.inputs || []).filter(i => i.link == null);

    // If the node has named inputs, use them
    if (node.inputs && node.inputs.length > 0) {
        for (const inp of node.inputs) {
            if (inp.link != null) {
                // Connected input → use link reference
                const link = linkMap[inp.link];
                if (link) {
                    nodeEntry.inputs[inp.name] = [String(link[1]), link[2]];
                }
            } else if (inp.widget) {
                // Widget input with metadata → need to find its value
                // Values are in widgets_values array, mapped by position among non-connected widgets
                // or if the input array has all widgets listed
            }
        }

        // Map widgets_values to widget inputs by position
        if (node.widgets_values && node.widgets_values.length > 0) {
            const widgetNames = (node.inputs || [])
                .filter(i => i.link == null)
                .map(i => i.name);
            
            for (let i = 0; i < Math.min(widgetNames.length, node.widgets_values.length); i++) {
                const val = node.widgets_values[i];
                if (val !== undefined && !(widgetNames[i] in nodeEntry.inputs)) {
                    nodeEntry.inputs[widgetNames[i]] = val;
                }
            }
        }
    } else {
        // No input metadata - fall back to positional mapping from schema
        // For SeedVR2 nodes, we've already fixed the order
        if (node.widgets_values && node.widgets_values.length > 0) {
            // Map by position - the order should match the class definition
            // We need to know the input order for each node type
            const schema = getSchemaForType(node.type);
            if (schema && schema.widgetNames) {
                for (let i = 0; i < Math.min(schema.widgetNames.length, node.widgets_values.length); i++) {
                    nodeEntry.inputs[schema.widgetNames[i]] = node.widgets_values[i];
                }
            } else {
                // Generic fallback
                for (let i = 0; i < node.widgets_values.length; i++) {
                    nodeEntry.inputs[`param_${i}`] = node.widgets_values[i];
                }
            }
        }
    }

    api[String(node.id)] = nodeEntry;
}

// Define known schemas for nodes without input metadata
function getSchemaForType(type) {
    const schemas = {
        'SeedVR2LoadDiTModel': {
            widgetNames: ['model', 'device', 'blocks_to_swap', 'swap_io_components', 'offload_device', 'cache_model', 'attention_mode']
        },
        'SeedVR2LoadVAEModel': {
            widgetNames: ['model', 'device', 'encode_tiled', 'encode_tile_size', 'encode_tile_overlap', 'decode_tiled', 'decode_tile_size', 'decode_tile_overlap', 'tile_debug', 'offload_device', 'cache_model']
        },
        'SeedVR2VideoUpscaler': {
            widgetNames: ['seed', 'resolution', 'max_resolution', 'batch_size', 'uniform_batch_size', 'temporal_overlap', 'prepend_frames', 'color_correction', 'input_noise_scale', 'latent_noise_scale', 'offload_device', 'enable_debug']
        },
        'FaceRestoreModelLoader': {
            widgetNames: ['model_name']
        },
        'Note': {
            widgetNames: ['text']
        }
    };
    return schemas[type] || null;
}

// Now handle connections for nodes that have input metadata but missing connected inputs
// Go through all links and add connections
for (const [linkId, link] of Object.entries(linkMap)) {
    const destNodeId = String(link[3]);
    const destSlot = link[4];
    const srcNodeId = String(link[1]);
    const srcSlot = link[2];

    if (api[destNodeId]) {
        const destNode = v6.nodes.find(n => n.id === link[3]);
        if (destNode && destNode.inputs) {
            const inputDef = destNode.inputs[destSlot];
            if (inputDef && inputDef.name && !(inputDef.name in api[destNodeId].inputs)) {
                api[destNodeId].inputs[inputDef.name] = [srcNodeId, srcSlot];
            }
        }
    }
}

// Also fix nodes where inputs are defined but connections weren't captured
for (const node of v6.nodes) {
    const nodeId = String(node.id);
    if (!api[nodeId]) continue;
    
    if (node.inputs) {
        for (const inp of node.inputs) {
            if (inp.link != null && !(inp.name in api[nodeId].inputs)) {
                const link = linkMap[inp.link];
                if (link) {
                    api[nodeId].inputs[inp.name] = [String(link[1]), link[2]];
                }
            }
        }
    }
}

// Write output
fs.writeFileSync('【优化版V7】QWEN-AIO-DWPose-VNCCS-API.json', JSON.stringify(api, null, 2), 'utf-8');
console.log('Converted ' + Object.keys(api).length + ' nodes to API format');
console.log('File: 【优化版V7】QWEN-AIO-DWPose-VNCCS-API.json');
