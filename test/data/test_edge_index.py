import os.path as osp
from typing import Optional

import pytest
import torch
from torch import Tensor

import torch_geometric
from torch_geometric.data.edge_index import EdgeIndex, matmul, to_dense
from torch_geometric.testing import (
    disableExtensions,
    onlyCUDA,
    onlyLinux,
    withCUDA,
    withPackage,
)
from torch_geometric.utils import scatter


def test_basic():
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sparse_size=(3, 3))
    assert isinstance(adj, EdgeIndex)
    assert str(adj) == ('EdgeIndex([[0, 1, 1, 2],\n'
                        '           [1, 0, 2, 1]])')
    assert adj.sparse_size == (3, 3)
    assert adj.sort_order is None

    assert not isinstance(adj.as_tensor(), EdgeIndex)

    assert not isinstance(adj + 1, EdgeIndex)


def test_fill_cache():
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')
    adj.validate().fill_cache()
    assert adj.sparse_size == (3, 3)
    assert torch.equal(adj._rowptr, torch.tensor([0, 1, 3, 4]))

    adj = EdgeIndex([[1, 0, 2, 1], [0, 1, 1, 2]], sort_order='col')
    adj.validate().fill_cache()
    assert adj.sparse_size == (3, 3)
    assert torch.equal(adj._colptr, torch.tensor([0, 1, 3, 4]))


@withCUDA
def test_to(device):
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]])

    out = adj.to(torch.int)
    assert isinstance(out, EdgeIndex)
    assert out.dtype == torch.int

    out = adj.to(torch.float)
    assert not isinstance(out, EdgeIndex)
    assert out.dtype == torch.float

    out = adj.to(device)
    assert isinstance(out, EdgeIndex)
    assert out.device == device


@onlyCUDA
def test_cpu_cuda():
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]])

    out = adj.cuda()
    assert isinstance(out, EdgeIndex)
    assert out.is_cuda

    out = out.cpu()
    assert isinstance(out, EdgeIndex)
    assert not out.is_cuda


def test_share_memory():
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')
    adj.fill_cache()

    adj = adj.share_memory_()
    assert isinstance(adj, EdgeIndex)
    assert adj.is_shared()
    assert adj._rowptr.is_shared()


def test_contiguous():
    data = torch.tensor([[0, 1], [1, 0], [1, 2], [2, 1]]).t()

    with pytest.raises(ValueError, match="needs to be contiguous"):
        EdgeIndex(data)

    adj = EdgeIndex(data.contiguous()).contiguous()
    assert isinstance(adj, EdgeIndex)
    assert adj.is_contiguous()


def test_sort_by():
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')
    out = adj.sort_by('row')
    assert isinstance(out, torch.return_types.sort)
    assert isinstance(out.values, EdgeIndex)
    assert not isinstance(out.indices, EdgeIndex)
    assert torch.equal(out.values, adj)
    assert torch.equal(out.indices, torch.arange(4))

    adj = EdgeIndex([[0, 1, 2, 1], [1, 0, 1, 2]])
    out = adj.sort_by('row')
    assert isinstance(out, torch.return_types.sort)
    assert isinstance(out.values, EdgeIndex)
    assert not isinstance(out.indices, EdgeIndex)
    assert torch.equal(out.values, torch.tensor([[0, 1, 1, 2], [1, 0, 2, 1]]))
    assert torch.equal(out.indices, torch.tensor([0, 1, 3, 2]))

    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')
    adj.fill_cache()

    out = adj.sort_by('col')
    assert torch.equal(out.values, torch.tensor([[1, 0, 2, 1], [0, 1, 1, 2]]))
    assert torch.equal(out.indices, torch.tensor([1, 0, 3, 2]))
    assert torch.equal(out.values._csr2csc, torch.tensor([1, 0, 3, 2]))

    out = out.values.sort_by('row')
    assert torch.equal(out.values, torch.tensor([[0, 1, 1, 2], [1, 0, 2, 1]]))
    assert torch.equal(out.indices, torch.tensor([1, 0, 3, 2]))
    assert torch.equal(out.values._csr2csc, torch.tensor([1, 0, 3, 2]))
    assert torch.equal(out.values._csc2csr, torch.tensor([1, 0, 3, 2]))

    # Do another round to sort based on `_csr2csc` and `_csc2csr`:
    out = out.values.sort_by('col')
    assert torch.equal(out.values, torch.tensor([[1, 0, 2, 1], [0, 1, 1, 2]]))
    assert torch.equal(out.indices, torch.tensor([1, 0, 3, 2]))
    assert torch.equal(out.values._csr2csc, torch.tensor([1, 0, 3, 2]))
    assert torch.equal(out.values._csc2csr, torch.tensor([1, 0, 3, 2]))

    out = out.values.sort_by('row')
    assert torch.equal(out.values, torch.tensor([[0, 1, 1, 2], [1, 0, 2, 1]]))
    assert torch.equal(out.indices, torch.tensor([1, 0, 3, 2]))
    assert torch.equal(out.values._csr2csc, torch.tensor([1, 0, 3, 2]))
    assert torch.equal(out.values._csc2csr, torch.tensor([1, 0, 3, 2]))


def test_cat():
    adj1 = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sparse_size=(3, 3))
    adj2 = EdgeIndex([[1, 2, 2, 3], [2, 1, 3, 2]], sparse_size=(4, 4))

    out = torch.cat([adj1, adj2], dim=1)
    assert out.size() == (2, 8)
    assert isinstance(out, EdgeIndex)
    assert out.sparse_size == (4, 4)
    assert out.sort_order is None

    out = torch.cat([adj1, adj2], dim=0)
    assert out.size() == (4, 4)
    assert not isinstance(out, EdgeIndex)


def test_flip():
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')
    adj.fill_cache()

    out = adj.flip(0)
    assert isinstance(out, EdgeIndex)
    assert torch.equal(out, torch.tensor([[1, 0, 2, 1], [0, 1, 1, 2]]))
    assert out.sparse_size == (3, 3)
    assert out.sort_order == 'col'
    assert torch.equal(out._colptr, torch.tensor([0, 1, 3, 4]))

    out = adj.flip([0, 1])
    assert isinstance(out, EdgeIndex)
    assert torch.equal(out, torch.tensor([[1, 2, 0, 1], [2, 1, 1, 0]]))
    assert out.sparse_size == (3, 3)
    assert out.sort_order is None
    assert out._colptr is None


def test_index_select():
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')

    out = adj.index_select(1, torch.tensor([1, 3]))
    assert torch.equal(out, torch.tensor([[1, 2], [0, 1]]))
    assert isinstance(out, EdgeIndex)

    out = adj.index_select(0, torch.tensor([0]))
    assert torch.equal(out, torch.tensor([[0, 1, 1, 2]]))
    assert not isinstance(out, EdgeIndex)


def test_narrow():
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')

    out = adj.narrow(dim=1, start=1, length=2)
    assert torch.equal(out, torch.tensor([[1, 1], [0, 2]]))
    assert isinstance(out, EdgeIndex)
    assert out.sort_order == 'row'

    out = adj.narrow(dim=0, start=0, length=1)
    assert torch.equal(out, torch.tensor([[0, 1, 1, 2]]))
    assert not isinstance(out, EdgeIndex)


def test_getitem():
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')

    out = adj[:, torch.tensor([False, True, False, True])]
    assert isinstance(out, EdgeIndex)
    assert torch.equal(out, torch.tensor([[1, 2], [0, 1]]))
    assert out.sort_order == 'row'

    out = adj[..., torch.tensor([1, 3])]
    assert isinstance(out, EdgeIndex)
    assert torch.equal(out, torch.tensor([[1, 2], [0, 1]]))
    assert out.sort_order is None

    out = adj[..., 1::2]
    assert isinstance(out, EdgeIndex)
    assert torch.equal(out, torch.tensor([[1, 2], [0, 1]]))
    assert out.sort_order == 'row'

    out = adj[:, 0]
    assert not isinstance(out, EdgeIndex)

    out = adj[torch.tensor([0])]
    assert not isinstance(out, EdgeIndex)


@pytest.mark.parametrize('dtype', [None, torch.double])
def test_to_dense(dtype):
    adj = EdgeIndex([[1, 0, 2, 1], [0, 1, 1, 2]])

    out = adj.to_dense(dtype=dtype)
    assert isinstance(out, Tensor)
    assert out.size() == (3, 3)
    assert out.dtype == dtype or torch.float
    assert out.tolist() == [[0, 1, 0], [1, 0, 1], [0, 1, 0]]

    value = torch.arange(1, 5, dtype=dtype or torch.float)
    out = to_dense(adj, value=value)
    assert isinstance(out, Tensor)
    assert out.size() == (3, 3)
    assert out.dtype == dtype or torch.float
    assert out.tolist() == [[0, 2, 0], [1, 0, 4], [0, 3, 0]]

    value = torch.arange(1, 5, dtype=dtype or torch.float).view(-1, 1)
    out = to_dense(adj, value=value)
    assert isinstance(out, Tensor)
    assert out.size() == (3, 3, 1)
    assert out.dtype == dtype or torch.float
    assert out.tolist() == [[[0], [2], [0]], [[1], [0], [4]], [[0], [3], [0]]]


def test_to_sparse_coo():
    adj = EdgeIndex([[1, 0, 2, 1], [0, 1, 1, 2]])
    if torch_geometric.typing.WITH_PT20:
        out = adj.to_sparse(layout=torch.sparse_coo)
    else:
        out = adj.to_sparse()
    assert isinstance(out, Tensor)
    assert out.layout == torch.sparse_coo
    assert out.size() == (3, 3)
    assert torch.equal(adj, out._indices())

    # Test clunky dispatch logic for `to_sparse_coo()`:
    adj = EdgeIndex([[1, 0, 2, 1], [0, 1, 1, 2]])
    out = adj.to_sparse_coo()
    assert isinstance(out, Tensor)
    assert out.layout == torch.sparse_coo
    assert out.size() == (3, 3)
    assert torch.equal(adj, out._indices())


def test_to_sparse_csr():
    with pytest.raises(ValueError, match="not sorted by rows"):
        EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]]).to_sparse_csr()

    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')
    if torch_geometric.typing.WITH_PT20:
        out = adj.to_sparse(layout=torch.sparse_csr)
    else:
        out = adj.to_sparse_csr()
    assert isinstance(out, Tensor)
    assert out.layout == torch.sparse_csr
    assert out.size() == (3, 3)
    assert torch.equal(adj._rowptr, out.crow_indices())
    assert torch.equal(adj[1], out.col_indices())


def test_to_sparse_csc():
    with pytest.raises(ValueError, match="not sorted by columns"):
        EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]]).to_sparse_csc()

    adj = EdgeIndex([[1, 0, 2, 1], [0, 1, 1, 2]], sort_order='col')
    if torch_geometric.typing.WITH_PT20:
        out = adj.to_sparse(layout=torch.sparse_csc)
    else:
        out = adj.to_sparse_csc()
    assert isinstance(out, Tensor)
    assert out.layout == torch.sparse_csc
    assert out.size() == (3, 3)
    assert torch.equal(adj._colptr, out.ccol_indices())
    assert torch.equal(adj[0], out.row_indices())


def test_matmul():
    x = torch.randn(3, 1)
    adj1 = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')
    adj2 = EdgeIndex([[1, 0, 2, 1], [0, 1, 1, 2]], sort_order='col')

    out = adj1 @ x
    assert torch.allclose(out, adj1.to_dense() @ x)

    out = adj2 @ x
    assert torch.allclose(out, adj2.to_dense() @ x)

    out = adj1 @ adj1
    assert torch.allclose(out.to_dense(), adj1.to_dense() @ adj1.to_dense())

    out = adj1 @ adj2
    assert torch.allclose(out.to_dense(), adj1.to_dense() @ adj2.to_dense())

    out = adj2 @ adj1
    assert torch.allclose(out.to_dense(), adj2.to_dense() @ adj1.to_dense())

    out = adj2 @ adj2
    assert torch.allclose(out.to_dense(), adj2.to_dense() @ adj2.to_dense())


def test_matmul_input_value():
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')

    x = torch.randn(3, 1)
    value = torch.randn(4)

    out = matmul(adj, x, input_value=value)
    assert torch.allclose(out, to_dense(adj, value=value) @ x)


def test_matmul_grad():
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')

    x1 = torch.randn(3, 1, requires_grad=True)
    value = torch.randn(4, requires_grad=True)

    out = matmul(adj, x1, input_value=value)
    grad_out = torch.randn_like(out)
    out.backward(grad_out)

    x2 = x1.detach().requires_grad_()
    dense_adj = to_dense(adj, value=value).detach().requires_grad_()
    out = dense_adj @ x2
    out.backward(grad_out)

    assert torch.allclose(x1.grad, x2.grad)
    if torch_geometric.typing.WITH_PT21:  # TODO Investigate.
        assert torch.allclose(value.grad, dense_adj.grad[adj[0], adj[1]])


def test_save_and_load(tmp_path):
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')
    adj.fill_cache()

    assert adj.sort_order == 'row'
    assert torch.equal(adj._rowptr, torch.tensor([0, 1, 3, 4]))

    path = osp.join(tmp_path, 'edge_index.pt')
    torch.save(adj, path)
    out = torch.load(path)

    assert isinstance(out, EdgeIndex)
    assert torch.equal(out, torch.tensor([[0, 1, 1, 2], [1, 0, 2, 1]]))
    assert out.sort_order == 'row'
    assert torch.equal(out._rowptr, torch.tensor([0, 1, 3, 4]))


@pytest.mark.parametrize('num_workers', [0, 2])
def test_data_loader(num_workers):
    adj = EdgeIndex([[0, 1, 1, 2], [1, 0, 2, 1]], sort_order='row')
    adj.fill_cache()

    loader = torch.utils.data.DataLoader(
        [adj] * 4,
        batch_size=2,
        num_workers=num_workers,
        collate_fn=lambda x: x,
        drop_last=True,
    )

    assert len(loader) == 2
    for batch in loader:
        assert isinstance(batch, list)
        assert len(batch) == 2
        for adj in batch:
            assert isinstance(adj, EdgeIndex)
            assert adj.is_shared() == (num_workers > 0)
            assert adj._rowptr.is_shared() == (num_workers > 0)


def test_torch_script():
    class Model(torch.nn.Module):
        def forward(self, x: Tensor, edge_index: EdgeIndex) -> Tensor:
            row, col = edge_index[0], edge_index[1]
            x_j = x[row]
            out = scatter(x_j, col, dim_size=edge_index.num_cols)
            return out

    x = torch.randn(3, 8)
    # Test that `num_cols` gets picked up by making last node isolated.
    edge_index = EdgeIndex([[0, 1, 1, 2], [1, 0, 0, 1]], sparse_size=(3, 3))

    model = Model()
    expected = model(x, edge_index)
    assert expected.size() == (3, 8)

    # `torch.jit.script` does not support inheritance at the `Tensor` level :(
    with pytest.raises(RuntimeError, match="attribute or method 'num_cols'"):
        torch.jit.script(model)

    # A valid workaround is to treat `EdgeIndex` as a regular PyTorch tensor
    # whenever we are in script mode:
    class ScriptableModel(torch.nn.Module):
        def forward(self, x: Tensor, edge_index: EdgeIndex) -> Tensor:
            row, col = edge_index[0], edge_index[1]
            x_j = x[row]
            dim_size: Optional[int] = None
            if (not torch.jit.is_scripting()
                    and isinstance(edge_index, EdgeIndex)):
                dim_size = edge_index.num_cols
            out = scatter(x_j, col, dim_size=dim_size)
            return out

    script_model = torch.jit.script(ScriptableModel())
    out = script_model(x, edge_index)
    assert out.size() == (2, 8)
    assert torch.allclose(out, expected[:2])


@onlyLinux
@disableExtensions
@withPackage('torch>=2.1.0')
def test_compile():
    import torch._dynamo as dynamo

    class Model(torch.nn.Module):
        def forward(self, x: Tensor, edge_index: EdgeIndex) -> Tensor:
            row, col = edge_index[0], edge_index[1]
            x_j = x[row]
            out = scatter(x_j, col, dim_size=edge_index.num_cols)
            return out

    x = torch.randn(3, 8)
    # Test that `num_cols` gets picked up by making last node isolated.
    edge_index = EdgeIndex([[0, 1, 1, 2], [1, 0, 0, 1]], sparse_size=(3, 3))

    model = Model()
    expected = model(x, edge_index)
    assert expected.size() == (3, 8)

    explanation = dynamo.explain(model)(x, edge_index)
    assert explanation.graph_break_count <= 0

    compiled_model = torch_geometric.compile(model)
    out = compiled_model(x, edge_index)
    assert torch.allclose(out, expected)
