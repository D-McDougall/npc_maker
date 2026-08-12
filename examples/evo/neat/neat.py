import json
import npc_maker.evo
import random
import copy

gin = 0

class NeatGenome(npc_maker.evo.Genome):
    def __init__(self):
        self.genes = []

    def parameters(self):
        genes = filter(lambda gene: not getattr(gene, 'disabled', False), self.genes)
        return [{attr: getattr(x, attr) for attr in x.__slots__} for x in genes]

    def mate(self, other):
        other_genes = {x.name: x for x in other.genes}
        child_genes = []
        for gene in self.genes:
            other_gene = other_genes.get(gene.name)
            if other_gene is not None:
                if getattr(gene, 'disabled', False) and getattr(other_gene, 'disabled', False):
                    disabled = True
                elif getattr(gene, 'disabled', False) or getattr(other_gene, 'disabled', False):
                    disabled = random.random() < 0.75
                else:
                    disabled = False
                # 
                if random.random() > 0.5:
                    gene = other_gene
                # 
                if disabled:
                    gene = copy.deepcopy(gene)
                    gene.disabled = True
            child_genes.append(gene)
        # 
        child = NeatGenome()
        child.genes = copy.deepcopy(child_genes)
        child.mutate()
        return child

    def mutate(self):
        edges = filter(lambda gene: isinstance(gene, Edge), self.genes)
        edges = filter(lambda edge: not edge.disabled, edges)
        nodes = filter(lambda gene: isinstance(gene, Node), self.genes)
        # Structural mutation: add node.
        if random.random() < 0.03:
            edges = list(edges)
            if not edges:
                return
            replace = random.choice(edges)
            replace.disabled = True
            node  = self.add_node()
            edge1 = self.add_edge(replace.presyn, node.name)
            edge2 = self.add_edge(node.name, replace.postsyn)
            edge1.weight = 1.0
            edge2.weight = replace.weight

        # Structural mutation: add edge.
        elif random.random() < 0.15:
            nodes = list(nodes)
            if len(nodes) < 2:
                return
            nodes = random.sample(nodes, 2)
            presyn = nodes[0].name
            postsyn = nodes[1].name
            # Check if the edge already exists.
            if any(edge.presyn == presyn and edge.postsyn == postsyn for edge in edges):
                return
            self.add_edge(presyn, postsyn)

        # Incremental mutation: modify an edge weight.
        elif random.random() < 0.80:
            delta = 1.0
            for node in nodes:
                if random.random() < 0.10:
                    node.midpoint = random.uniform(-1.0, 1.0)
                else:
                    node.midpoint += random.uniform(-delta, delta)

            for edge in edges:
                if random.random() < 0.10:
                    edge.weight = random.uniform(-1.0, 1.0)
                else:
                    edge.weight += random.uniform(-delta, delta)

    def distance(self, other):
        c1 = 1.0
        c2 = 0.4
        # Find the matching genes.
        self_genes      = {x.name: x for x in self.genes if isinstance(x, Edge)}
        other_genes     = {x.name: x for x in other.genes if isinstance(x, Edge)}
        distance        = 0.0
        for name, gene in self_genes.items():
            if name in other_genes:
                if isinstance(gene, Node):
                    distance += abs(gene.midpoint - other_genes[name].midpoint)
                elif isinstance(gene, Edge):
                    distance += abs(gene.weight - other_genes[name].weight)
        # Count the excess/disjoint genes.
        self_genes      = set(self_genes)
        other_genes     = set(other_genes)
        num_disjoint    = len(self_genes.symmetric_difference(other_genes))
        return c1 * num_disjoint + c2 * distance

    def add_node(self):
        global gin
        node = Node()
        node.type = "Node"
        node.name = gin
        gin += 1
        node.slope = 1.0
        node.midpoint = random.uniform(-1, 1)
        self.genes.append(node)
        return node

    def add_edge(self, presyn, postsyn):
        global gin
        node = Edge()
        node.type = "Edge"
        node.name = gin
        gin += 1
        node.weight = random.uniform(-1, 1)
        node.presyn = presyn
        node.postsyn = postsyn
        node.disabled = False
        self.genes.append(node)
        return node

    def save(self):
        return self.parameters()

    @classmethod
    def load(cls, data):
        self = cls()
        for x in data:
            y = Node() if x["type"] == "Node" else Edge()
            for attr, value in x.items():
                setattr(y, attr, value)
            self.genes.append(y)

class Node:
    __slots__ = ('name', 'type', 'slope', 'midpoint')

class Edge:
    __slots__ = ('name', 'type', 'presyn', 'postsyn', 'weight', 'disabled')
